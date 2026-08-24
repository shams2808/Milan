"""Self-check:  python -m milan.test_milan

No pytest. Most of these encode a bug that actually shipped and was caught by
making the synthetic data harder -- see INCIDENTS.md. They exist so those bugs
cannot come back.
"""

from datetime import date

from .core import Invoice, norm_loose, norm_strict
from .match import _edit_distance, _is_coded, reconcile, AMOUNT, BYVALUE, EXACT
from .report import classify_unclaimed, evaluate, pan_conflicts, suspected_gstin_typos
from .synth import build_year

GST_A = "27AABCU9603R1ZM"
GST_B = "27AABCU9603R1ZN"


def _inv(source, no, tax=1000.0, day=10, gstin=GST_A, rid=None):
    return Invoice(
        gstin=gstin, supplier="Test Co", inv_no=no,
        inv_date=date(2025, 6, day), taxable=tax * 5, igst=tax,
        source=source, row_id=rid or f"{source}{no}{day}{tax}",
    )


def test_normaliser_does_not_eat_the_invoice_number():
    # The FY regex used to match "06/25" INSIDE "006/25-26", collapsing 006,
    # 029 and 003 all onto "26". Three invoices, one key.
    assert norm_loose("006/25-26") == "6"
    assert norm_loose("029/25-26") == "29"
    assert norm_loose("003/25-26") == "3"
    assert norm_loose("123/25-26") == "123"
    assert len({norm_loose(x) for x in ("006/25-26", "029/25-26", "003/25-26")}) == 3


def test_normaliser_strips_glued_prefix():
    # \b found no boundary between GST and 00006, so this never stripped.
    assert norm_loose("GST00006") == "6"
    assert norm_loose("INV/2025-26/0001") == "1"
    assert norm_loose("INV-25-26-1") == "1"
    assert norm_loose("BILL-003") == "3"


def test_normaliser_keeps_identity_when_everything_looks_like_noise():
    assert norm_loose("2025") == "2025"
    assert norm_strict("INV/2025-26/0001") == "INV2025260001"


def test_transposition_costs_one_edit():
    # Plain Levenshtein scores this 2 (delete + insert), so the commonest
    # typing error looked like an unrelated invoice.
    assert _edit_distance("12", "21") == 1
    assert _edit_distance("12", "13") == 1
    assert _edit_distance("12", "99") == 2


def test_supplier_code_survives_leading_zeros():
    assert _is_coded("12", "SEL0012")
    assert _is_coded("12", "SEL12")
    assert not _is_coded("12", "99912")


def test_never_matches_across_gstin():
    """The practitioner's hard rule: the GST number must be the same."""
    res = reconcile([_inv("TALLY", "0001", gstin=GST_A)],
                    [_inv("2A", "0001", gstin=GST_B)])
    assert res.pairs == []
    assert len(res.only_tally) == 1 and len(res.only_gstr) == 1


def test_same_number_months_apart_is_not_a_match():
    t = _inv("TALLY", "0001", day=2)
    g = Invoice(gstin=GST_A, supplier="Test Co", inv_no="0001",
                inv_date=date(2025, 11, 15), taxable=5000.0, igst=1000.0,
                source="2A", row_id="g1")
    assert reconcile([t], [g]).pairs == []


def test_value_and_date_refuses_two_readable_numbers():
    """Recurring billers charge an identical amount every month. Matching on
    value alone across two perfectly readable, different numbers is how you
    confidently claim the wrong invoice."""
    res = reconcile([_inv("TALLY", "GST00010")], [_inv("2A", "GST00006")])
    assert all(p.stage != BYVALUE for p in res.pairs)
    assert res.pairs == []


def test_value_and_date_still_rescues_a_blank_number():
    res = reconcile([_inv("TALLY", "")], [_inv("2A", "GST00006")])
    assert len(res.pairs) == 1 and res.pairs[0].stage == BYVALUE


def test_amount_mismatch_is_reported_not_hidden():
    res = reconcile([_inv("TALLY", "0001", tax=1000.0)],
                    [_inv("2A", "0001", tax=1500.0)])
    assert len(res.pairs) == 1
    assert res.pairs[0].stage == AMOUNT
    assert res.pairs[0].tax_delta == -500.0


def test_gstin_typo_is_surfaced_not_auto_matched():
    bad = GST_A[:6] + "0" + GST_A[7:]
    res = reconcile([_inv("TALLY", "0001", gstin=bad)], [_inv("2A", "0001")])
    assert res.pairs == [], "must not silently match across GSTINs"
    assert len(suspected_gstin_typos(res)) == 1, "but must tell the advocate"


def test_end_to_end_accuracy():
    tally, gstr, planted = build_year(n_invoices=800, seed=11)
    res = reconcile(tally, gstr)
    ev = evaluate(res, planted)
    # A false match wrongly claims ITC and draws interest u/s 50. A missed
    # match only lands on a human's review list. Precision matters more.
    assert ev["wrong"] == 0, f"wrong matches: {ev['wrong']}"
    assert ev["recall"] > 0.95, ev["recall"]


def test_pan_conflicts_do_not_double_count():
    """A supplier filing from three GSTINs under one PAN must not have its
    books invoices counted once per portal GSTIN it happens to be compared
    against. Regression for a real bug: joining every books-GSTIN against
    every portal-GSTIN sharing a PAN summed the same 4 invoices twice."""
    d = date(2025, 6, 10)
    books = Invoice(gstin="07AABCR0347P1Z5", supplier="Redington", inv_no="A1",
                     inv_date=d, taxable=1000.0, igst=180.0,
                     source="TALLY", row_id="t1")
    p1 = Invoice(gstin="10AABCR0347P1ZI", supplier="Redington", inv_no="B1",
                 inv_date=d, taxable=2000.0, igst=360.0, source="2A", row_id="g1")
    p2 = Invoice(gstin="27AABCR0347P1Z3", supplier="Redington", inv_no="C1",
                 inv_date=d, taxable=3000.0, igst=540.0, source="2A", row_id="g2")

    res = reconcile([books], [p1, p2])
    conflicts = pan_conflicts(res, [books], [p1, p2])
    assert len(conflicts) == 1, "one PAN, one row -- not one row per GSTIN pair"

    total_from_conflicts = sum(c[6] for c in conflicts)
    total_from_bucket = sum(
        i.tax for i in classify_unclaimed(res, [books]).get("other_registration", [])
    )
    assert total_from_conflicts == total_from_bucket == p1.tax + p2.tax


def test_matching_is_one_to_one():
    tally, gstr, _ = build_year(n_invoices=400, seed=5)
    res = reconcile(tally, gstr)
    assert len({p.tally.row_id for p in res.pairs}) == len(res.pairs)
    assert len({p.gstr.row_id for p in res.pairs}) == len(res.pairs)


def test_workbook_sheets_are_disjoint_and_complete():
    """Every unmatched invoice appears on exactly one sheet.

    Replaces a test that could not fail: it never called write_workbook, never
    opened the file, and its only assertion was that a sum of taxes is >= 0.
    Meanwhile other_registration sat on two sheets and supplier_absent was
    split across two more by a rupee threshold.
    """
    from .report import classify_ineligible, classify_unclaimed

    tally, gstr, _ = build_year(n_invoices=300, seed=7)
    res = reconcile(tally, gstr)
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)

    sheets = {
        "Not in Tally": [i.row_id for i in unclaimed.get("missing_invoice", [])],
        "Not in 2A": [i.row_id for i in ineligible.get("not_filed", [])
                      + ineligible.get("supplier_absent", [])],
        "Other Ledgers": [i.row_id for i in unclaimed.get("supplier_absent", [])],
        "Partial (conflicts)": [i.row_id for i in unclaimed.get("other_registration", [])
                                + ineligible.get("other_registration", [])],
    }
    seen = {}
    for name, ids in sheets.items():
        for rid in ids:
            assert rid not in seen, f"{rid} on both {seen[rid]} and {name}"
            seen[rid] = name

    every_unmatched = {i.row_id for i in res.only_tally} | {i.row_id for i in res.only_gstr}
    assert set(seen) == every_unmatched, (
        f"unplaced: {len(every_unmatched - set(seen))}, invented: {len(set(seen) - every_unmatched)}"
    )


def test_workbook_file_is_valid_and_readable():
    """Write a real workbook and read it back.

    Guards the corruption class of bug: 5,757 text cells were emitted as
    <is><t>..</t></is> without t="inlineStr", and <pane> was written bare after
    </sheetData>. Both make Excel declare the file corrupt. Neither is visible
    unless something actually parses the output.
    """
    import re as _re
    import tempfile
    import zipfile
    from .workbook import write_workbook
    from .xlsx_lite import Workbook as Reader

    tally, gstr, _ = build_year(n_invoices=200, seed=3)
    res = reconcile(tally, gstr)
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/wb.xlsx"
        write_workbook(path, tally, gstr, res)

        with zipfile.ZipFile(path) as z:
            for part in z.namelist():
                if "worksheets/sheet" not in part or not part.endswith(".xml"):
                    continue
                xml = z.read(part).decode("utf-8")
                for m in _re.finditer(r"<c [^>]*>(?=<is>)", xml):
                    assert "inlineStr" in m.group(0), f"{part}: <is> without t=inlineStr"
                assert not _re.search(r"</sheetData>\s*<pane", xml), f"{part}: bare <pane>"
                if "<sheetViews>" in xml:
                    assert xml.index("<sheetViews>") < xml.index("<sheetData>"), part

        reader = Reader(path)
        names = reader.sheet_names()
        assert names[0] == "Summary" and "Partial Mismatch" in names

        rows = list(reader.rows("Not in Tally"))
        assert rows[0]["A"] == "Supplier", "header text must survive the round trip"
        if len(rows) > 1:
            assert rows[1]["A"], "supplier name must not come back blank"


def test_partial_mismatch_ignores_single_character_typos():
    """The practitioner said MAJOR bill-number differences. A one-character
    typo is a match, not a mismatch, and must not clutter the sheet."""
    from .workbook import partial_mismatches

    t = _inv("TALLY", "2526021990")
    g = _inv("2A", "252601990")
    res = reconcile([t], [g])
    assert len(res.pairs) == 1, "should still match"
    assert partial_mismatches(res) == [], "one edit apart is not a mismatch"


def test_partial_mismatch_catches_date_and_taxable_differences():
    """Date and taxable-value differences were both criteria the practitioner
    named, and neither was being checked at all."""
    from .workbook import partial_mismatches

    t = Invoice(gstin=GST_A, supplier="X", inv_no="0001", inv_date=date(2025, 6, 18),
                taxable=5000.0, igst=1000.0, source="TALLY", row_id="t1")
    g = Invoice(gstin=GST_A, supplier="X", inv_no="0001", inv_date=date(2025, 6, 10),
                taxable=4000.0, igst=1000.0, source="2A", row_id="g1")
    res = reconcile([t], [g])
    mm = partial_mismatches(res)
    assert len(mm) == 1
    reasons = mm[0][1]
    assert "Bill date" in reasons and "Taxable amount" in reasons, reasons
    assert mm[0][4] == 8, "day delta"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
