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


def test_never_matches_across_unrelated_companies():
    """Unrelated companies (different PAN) must never match across GSTIN."""
    gst_c = "06AAACT9999K1ZZ"
    res = reconcile([_inv("TALLY", "0001", gstin=GST_A)],
                    [_inv("2A", "0001", gstin=gst_c)])
    assert res.pairs == []
    assert len(res.only_tally) == 1 and len(res.only_gstr) == 1


def test_same_pan_different_gstin_matches_as_gstin_conflict():
    """Same company (PAN), different state GSTIN matches and routes to partial mismatch."""
    res = reconcile([_inv("TALLY", "0001", gstin=GST_A)],
                    [_inv("2A", "0001", gstin=GST_B)])
    assert len(res.pairs) == 1
    assert res.pairs[0].stage == "gstin_conflict"
    from .workbook import partial_mismatches
    pm = partial_mismatches(res)
    assert len(pm) == 1
    assert "GST number" in pm[0][1]


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
    res = reconcile([_inv("TALLY", "GST00010", day=2)], [_inv("2A", "GST00006", day=25)])
    assert all(p.stage != BYVALUE for p in res.pairs)
    assert res.pairs == []


def test_amount_match_with_different_bill_number_routes_to_partial_mismatch():
    """When amount and date match but bill number differs (e.g. City Computers 4030 vs 4029),
    match and route to partial mismatch rather than unfiled / unbooked."""
    res = reconcile([_inv("TALLY", "4029", tax=273.0, day=14)],
                    [_inv("2A", "4030", tax=273.0, day=14)])
    assert len(res.pairs) == 1
    assert res.pairs[0].stage == "amount_date_diff_inv"
    from .workbook import partial_mismatches
    pm = partial_mismatches(res)
    assert len(pm) == 1
    assert "Bill number" in pm[0][1]


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
        "Credit Notes Not Booked": [i.row_id for i in
                                    unclaimed.get("unrecorded_credit_note", [])],
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


def test_partial_mismatch_ignores_prefix_and_software_variants():
    """The practitioner was explicit: 'UPNUP0068' vs 'UP0068' is the same
    bill, just a different way of typing the invoice number.
    Recognized branch/prefix variants and supplier codes must NOT be flagged
    as partial mismatches on the bill number when tax and date agree."""
    from .workbook import partial_mismatches

    t = _inv("TALLY", "UP0068", tax=8496.0)
    g = _inv("2A", "UPNUP0068", tax=8496.0)
    res = reconcile([t], [g])
    assert len(res.pairs) == 1
    assert partial_mismatches(res) == [], "prefix variant (UP vs UPNUP) is not a partial mismatch"



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


def test_draft_may_not_invent_or_round_a_figure():
    """The guardrail that lets a model near a document a GST officer reads.

    The practitioner's position on AI deciding anything was "our experience
    tells us more than your AI model", which is correct and settles it: the
    model writes prose, the figures are computed. A draft that rounds
    Rs 28,713 to "approximately Rs 29,000" has invented a liability, so any
    number not present in the computed facts is reported and the draft fails.
    """
    from .remediate import Action, verify_draft

    a = Action(kind="chase_supplier", title="t", recipient="X",
               facts={"invoice_count": 4, "total_tax": 15418.32,
                      "supplier_name": "Redington"})

    faithful = "We refer to 4 invoices totalling Rs 15,418.32 in tax."
    assert verify_draft(a, faithful) == [], verify_draft(a, faithful)

    assert verify_draft(a, "approximately Rs 29,000 in tax") == ["29,000"]
    assert "7" in verify_draft(a, "4 invoices and 7 credit notes")


def test_plan_makes_one_action_per_non_filing_supplier():
    from .remediate import CHASE_SUPPLIER, plan

    tally, gstr, _ = build_year(n_invoices=300, seed=7)
    res = reconcile(tally, gstr)
    actions = plan(res, tally, gstr)

    chases = [a for a in actions if a.kind == CHASE_SUPPLIER]
    from .report import classify_ineligible
    expected = {(i.gstin, i.supplier) for i in classify_ineligible(res, gstr).get("not_filed", [])}
    assert len(chases) == len(expected)
    # Every figure quoted is the real one, so a draft can never exceed it.
    for a in chases:
        assert a.facts["total_tax"] == round(sum(i.tax for i in a.invoices), 2)


def test_load_gstr3b_and_verify_totals():
    from pathlib import Path
    from .loaders import load_gstr3b
    p = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx")
    if not p.exists():
        return
    s = load_gstr3b(str(p))
    assert s.total_itc_non_rev == 53976364.20
    assert s.total_itc_rev == 8081.12
    assert s.total_tax_liability == 62581575.00
    assert s.total_cash_offset == 10022668.00
    assert s.opening_balance == 79522.00
    assert s.closing_balance == 1491792.00
    assert len(s.months) == 12
    assert s.months["April"].itc_non_rev == 2494267.76


def test_load_gstr2a_filing_period():
    from pathlib import Path
    from .loaders import load_gstr2a
    p = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    if not p.exists():
        return
    rows = load_gstr2a(str(p))
    assert len(rows) > 0
    assert rows[0].filing_period == "042025"
    assert any(r.filing_period for r in rows)


def test_three_way_position_and_timing():
    from pathlib import Path
    from .loaders import load_gstr2a, load_gstr3b, load_tally
    from .report import compute_three_way_position
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    p_3b = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx")
    if not (p_2a.exists() and p_tally.exists() and p_3b.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    g3b = load_gstr3b(str(p_3b))
    res = reconcile(tally, gstr)
    pos = compute_three_way_position(tally, gstr, res, g3b)

    assert pos.available_2a == 57441592.32
    assert pos.booked_tally == 56057647.31
    assert pos.matched_tax == 55973229.52
    assert pos.claimed_3b == 53976364.20
    assert pos.matched_unclaimed == 1996865.32
    assert pos.gap_2a_3b == 3465228.12
    assert len(pos.monthly) == 12


def test_forecaster_and_rule_88d():
    from pathlib import Path
    from .forecaster import compute_finops_forecast
    from .loaders import load_gstr2a, load_gstr3b, load_tally
    from .report import compute_three_way_position
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    p_3b = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx")
    if not (p_2a.exists() and p_tally.exists() and p_3b.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    g3b = load_gstr3b(str(p_3b))
    res = reconcile(tally, gstr)
    pos = compute_three_way_position(tally, gstr, res, g3b)
    fc = compute_finops_forecast(tally, gstr, res, pos, g3b)

    assert fc.rule_88d.risk_level == "SAFE"
    assert not fc.rule_88d.is_drc01c_imminent
    assert fc.cash_forecast.closing_itc_balance == 1491792.00
    assert fc.sec_50_interest.annual_interest_rate == 18.0
    assert fc.sec_50_interest.invoice_count > 0


def test_vendor_risk_and_ims():
    from pathlib import Path
    from .loaders import load_gstr2a, load_tally
    from .vendor_risk import evaluate_vendor_risk
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    if not (p_2a.exists() and p_tally.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    res = reconcile(tally, gstr)
    vendors, summary = evaluate_vendor_risk(tally, gstr, res)

    assert len(vendors) > 0
    assert summary.total_vendors_analyzed == len(vendors)
    assert summary.grade_a_count > 0
    assert any(v.grade in ("C", "D") for v in vendors)
    assert any(v.ims_action == "ACCEPT" for v in vendors)


def test_copilot_deterministic_qa():
    from pathlib import Path
    from .copilot import ask_copilot
    from .forecaster import compute_finops_forecast
    from .loaders import load_gstr2a, load_gstr3b, load_tally
    from .report import compute_three_way_position
    from .vendor_risk import evaluate_vendor_risk
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    p_3b = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx")
    if not (p_2a.exists() and p_tally.exists() and p_3b.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    g3b = load_gstr3b(str(p_3b))
    res = reconcile(tally, gstr)
    pos = compute_three_way_position(tally, gstr, res, g3b)
    fc = compute_finops_forecast(tally, gstr, res, pos, g3b)
    vendors, summary = evaluate_vendor_risk(tally, gstr, res)

    r1 = ask_copilot("Who are our top risk suppliers?", tally, gstr, res, pos, g3b, fc, vendors, summary)
    assert r1.intent == "vendor_risk"
    assert len(r1.action_items) > 0

    r2 = ask_copilot("What is our Section 16(4) lapse exposure?", tally, gstr, res, pos, g3b, fc, vendors, summary)
    assert r2.intent == "section_16_4"
    assert "30 November" in r2.answer_html

    r3 = ask_copilot("Forecast next month cash outflow", tally, gstr, res, pos, g3b, fc, vendors, summary)
    assert r3.intent == "cash_forecast"


def test_dispute_notice_generation():
    from pathlib import Path
    from .loaders import load_gstr2a, load_tally
    from .remediate import CHASE_SUPPLIER, generate_legal_chase_notice, plan, verify_draft
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    if not (p_2a.exists() and p_tally.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    res = reconcile(tally, gstr)
    actions = plan(res, tally, gstr)
    chase = [a for a in actions if a.kind == CHASE_SUPPLIER]
    if chase:
        draft = generate_legal_chase_notice(chase[0])
        assert "SECTION 16(2)(c)" in draft
        invented = verify_draft(chase[0], draft)
        assert len(invented) == 0, f"Invented numbers found: {invented}"


def test_workbook_six_sheets_when_3b_present():
    import tempfile
    from pathlib import Path
    from .loaders import load_gstr2a, load_gstr3b, load_tally
    from .workbook import write_workbook
    from .xlsx_lite import Workbook
    p_2a = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx")
    p_tally = Path("milan/Data/Heamons/DayBook.xlsx")
    p_3b = Path("milan/Data/Heamons/07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx")
    if not (p_2a.exists() and p_tally.exists() and p_3b.exists()):
        return
    gstr = load_gstr2a(str(p_2a))
    tally, _ = load_tally([str(p_tally)])
    g3b = load_gstr3b(str(p_3b))
    res = reconcile(tally, gstr)

    tmp = Path(tempfile.gettempdir()) / "milan_test_6sheets.xlsx"
    write_workbook(str(tmp), tally, gstr, res, gstr3b=g3b)
    wb = Workbook(str(tmp))
    assert len(wb.sheet_names()) in (6, 7)
    assert "ITC Position" in wb.sheet_names()
    assert "Summary" in wb.sheet_names()

def test_busy_register_loading_and_reconciliation():
    from pathlib import Path
    from .loaders import load_gstr2a, load_tally, load_books
    from .match import reconcile

    p_busy_up = Path("milan/Data/GCI/UP/Purchase register GCI-U.P.xlsx")
    p_2a_up = Path("milan/Data/GCI/UP/09AAMFG9763A1Z4_GSTR2A_ANNUAL_Summary(2025-2026)U.P.xlsx")

    if not (p_busy_up.exists() and p_2a_up.exists()):
        return

    # 1. Test load_books / load_tally on Busy
    busy_invs, counts = load_books([str(p_busy_up)])
    assert len(busy_invs) == 282
    assert "B2B" in counts

    # Check multi-rate aggregation on invoice 138 (Row 13 + Row 14)
    tyre = next(i for i in busy_invs if i.inv_no == "138")
    assert tyre.tax == 365.26
    assert tyre.taxable == 1334.74

    # 2. Test reconciliation against 2A
    gstr = load_gstr2a(str(p_2a_up))
    res = reconcile(busy_invs, gstr)
    assert len(res.pairs) == 279
    assert sum(p.gstr.tax for p in res.pairs) > 8600000

    # Specifically test Nulith UPNUP0093 vs UP0093
    nulith_pair = next(p for p in res.pairs if p.tally.inv_no == "UP0093")
    assert nulith_pair.gstr.inv_no == "UPNUP0093"
    assert nulith_pair.stage == "supplier_prefix_variant"
    assert nulith_pair.tally.tax == 65901.6

    # Test Panamax sister GSTIN match (07... in Tally vs 06... in 2A)
    panamax_pair = next(p for p in res.pairs if p.tally.inv_no == "KUN-1889-25-26")
    assert panamax_pair.stage == "gstin_conflict"
    assert panamax_pair.tally.gstin == "07AALCP6741K1ZX"
    assert panamax_pair.gstr.gstin == "06AALCP6741K1ZZ"
    assert panamax_pair.tally.tax == 13744.8

    # Test City Computers amount and date match with 1-digit bill number diff
    city_pair = next(p for p in res.pairs if p.tally.inv_no == "Cc/4029/25-26")
    assert city_pair.stage == "amount_date_diff_inv"
    assert city_pair.tally.inv_no == "Cc/4029/25-26"
    assert city_pair.gstr.inv_no == "CC/4030/25-26"


def test_supplier_prefix_variant_nulith_match():
    """Verify that branch/software prefixes (e.g. UPNUP0093 vs UP0093)
    match cleanly when GSTIN, tax and date agree."""
    t = _inv("TALLY", "UP0093", tax=65901.60)
    g = _inv("2A", "UPNUP0093", tax=65901.60)
    res = reconcile([t], [g])
    assert len(res.pairs) == 1
    assert res.pairs[0].stage == "supplier_prefix_variant"
    assert res.pairs[0].tally.inv_no == "UP0093"
    assert res.pairs[0].gstr.inv_no == "UPNUP0093"


def test_numeric_suffix_and_format_match():
    """Verify that trailing document digits match (e.g. NDSPL252680791 vs 791,
    DUN-4-1-25-26 vs DUN-4-01-25-26)."""
    t1 = _inv("TALLY", "791", tax=2790.0, rid="t1")
    g1 = _inv("2A", "NDSPL252680791", tax=2790.0, rid="g1")
    res1 = reconcile([t1], [g1])
    assert len(res1.pairs) == 1
    assert res1.pairs[0].stage == "supplier_prefix_variant"

    t2 = _inv("TALLY", "DUN-4-1-25-26", tax=4780.8, rid="t2")
    g2 = _inv("2A", "DUN-4-01-25-26", tax=4780.8, rid="g2")
    res2 = reconcile([t2], [g2])
    assert len(res2.pairs) == 1
    assert res2.pairs[0].stage == "supplier_prefix_variant"


def test_gstr2a_cdnr_loading_and_reconciliation():
    """Verify that CDNR sheet credit/debit notes are parsed with appropriate signs."""
    from pathlib import Path
    from .loaders import load_gstr2a
    p = Path("milan/Data/GCI/UP/09AAMFG9763A1Z4_GSTR2A_ANNUAL_Summary(2025-2026)U.P.xlsx")
    if not p.exists():
        return
    rows = load_gstr2a(str(p))
    cdnr_rows = [r for r in rows if r.source == "2A_CDNR"]
    assert len(cdnr_rows) == 17
    assert any(r.tax < 0 for r in cdnr_rows)  # Credit notes (negative ITC)
    assert any(r.tax > 0 for r in cdnr_rows)  # Debit notes (positive ITC)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")



