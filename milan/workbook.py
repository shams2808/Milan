"""Build the review workbook: one file, five sheets, the practitioner's headings.

The headings are theirs, not mine: "not in tally", "not in 2A", "partial
mismatch (both bills as per 2A and Tally must be visible together)". A flat
580-row CSV was correct and unreadable; this is the same findings arranged the
way they already think about the problem.

SHEET MEMBERSHIP IS EXHAUSTIVE AND DISJOINT. Every unmatched invoice lands on
exactly one sheet, and every matched pair with a real difference lands on
exactly one row of Partial Mismatch:

    only_gstr  = missing_invoice -> "Not in Tally"
                 other_registration -> "Partial Mismatch" (section B)
                 supplier_absent -> "Other Ledgers (FYI)"
    only_tally = not_filed + supplier_absent -> "Not in 2A"
                 other_registration -> "Partial Mismatch" (section B)

An earlier version put other_registration on BOTH "Not in Tally" and the
mismatch sheet, and split supplier_absent across two sheets by a rupee
threshold, so the same invoice appeared twice and the sheet totals could not
be reconciled against the report. test_workbook_sheets_are_disjoint pins it.
"""

from __future__ import annotations

from collections import defaultdict

from .core import TAX_TOLERANCE, Invoice, pan, rupees
from .match import Result, _edit_distance
from .report import ITC_DEADLINE, classify_ineligible, classify_unclaimed, pan_conflicts
from .xlsx_write import Workbook

# cellXfs indices defined in xlsx_write._styles_xml
S_HEADER, S_MONEY = 1, 2

_LEDGER_COLS = ["Supplier", "GSTIN", "Invoice No", "Date",
                "Taxable", "IGST", "CGST", "SGST", "Total Tax", "Why", "Action"]
_LEDGER_WIDTHS = {0: 38, 1: 18, 2: 22, 3: 12, 4: 13, 5: 11, 6: 11, 7: 11, 8: 13, 9: 40, 10: 38}

_PAIR_COLS = ["Supplier", "What Differs",
              "2A GSTIN", "2A Invoice No", "2A Date", "2A Taxable", "2A Tax",
              "Tally GSTIN", "Tally Invoice No", "Tally Date", "Tally Taxable", "Tally Tax",
              "Taxable Diff", "Tax Diff", "Days Apart"]
_PAIR_WIDTHS = {0: 34, 1: 22, 2: 18, 3: 22, 4: 12, 5: 13, 6: 12,
                7: 18, 8: 22, 9: 12, 10: 13, 11: 12, 12: 13, 13: 12, 14: 11}


def partial_mismatches(res: Result) -> list[tuple]:
    """Matched pairs where the two documents genuinely differ.

    The practitioner's own criteria: a taxable-amount difference, a tax
    difference, a MAJOR bill-number difference, or a bill-date difference.
    "Major" is load-bearing -- they were explicit that a one-character typo is
    a match, not a mismatch, so a single-edit difference is not reported here.

    Returns (pair, reasons, taxable_delta, tax_delta, day_delta).
    """
    out = []
    for p in res.pairs:
        d_taxable = round(p.tally.taxable - p.gstr.taxable, 2)
        d_tax = round(p.tally.tax - p.gstr.tax, 2)
        d_days = (p.tally.inv_date - p.gstr.inv_date).days

        reasons = []
        if abs(d_taxable) > TAX_TOLERANCE:
            reasons.append("Taxable amount")
        if abs(d_tax) > TAX_TOLERANCE:
            reasons.append("Tax amount")
        if d_days:
            reasons.append("Bill date")
        if p.tally.loose != p.gstr.loose and _edit_distance(p.tally.loose, p.gstr.loose) >= 2:
            reasons.append("Bill number")

        if reasons:
            out.append((p, reasons, d_taxable, d_tax, d_days))
    return sorted(out, key=lambda x: -max(abs(x[2]), abs(x[3]), abs(x[4]) * 1000))


def gstin_conflict_rows(res: Result, tally: list[Invoice], gstr: list[Invoice]) -> list[list]:
    """Section B: same supplier PAN, two GST registrations.

    Pairs a books row against a portal row on (PAN, normalised invoice number,
    tax) so both bills sit on ONE line, which is the whole point of the sheet.
    Rows that cannot be paired are still listed, with the counterpart side left
    blank -- dropping them would hide real money (Ingram Micro alone is Rs 5.2L).
    """
    t_orr = classify_ineligible(res, gstr).get("other_registration", [])
    g_orr = classify_unclaimed(res, tally).get("other_registration", [])

    index: dict[tuple, list[Invoice]] = defaultdict(list)
    for g in g_orr:
        index[(pan(g.gstin), g.strict, round(g.tax, 2))].append(g)

    rows, used_g = [], set()
    for t in sorted(t_orr, key=lambda i: -i.tax):
        key = (pan(t.gstin), t.strict, round(t.tax, 2))
        mate = next((g for g in index.get(key, []) if g.row_id not in used_g), None)
        if mate is not None:
            used_g.add(mate.row_id)
            rows.append([
                t.supplier, "GST number",
                mate.gstin, mate.inv_no, mate.inv_date.isoformat(), mate.taxable, mate.tax,
                t.gstin, t.inv_no, t.inv_date.isoformat(), t.taxable, t.tax,
                round(t.taxable - mate.taxable, 2), round(t.tax - mate.tax, 2), 0,
            ])
        else:
            rows.append([
                t.supplier, "GST number (in Tally only)",
                "", "", "", "", "",
                t.gstin, t.inv_no, t.inv_date.isoformat(), t.taxable, t.tax,
                "", "", "",
            ])

    for g in sorted(g_orr, key=lambda i: -i.tax):
        if g.row_id in used_g:
            continue
        rows.append([
            g.supplier, "GST number (in 2A only)",
            g.gstin, g.inv_no, g.inv_date.isoformat(), g.taxable, g.tax,
            "", "", "", "", "",
            "", "", "",
        ])
    return rows


def _ledger_rows(invoices: list[Invoice], why: str, action: str) -> list[list]:
    return [[i.supplier, i.gstin, i.inv_no, i.inv_date.isoformat(),
             i.taxable, i.igst, i.cgst, i.sgst, i.tax, why, action]
            for i in sorted(invoices, key=lambda x: -x.tax)]


def _money_styles(rows: list[list], cols: list[int], first_data_row: int = 1) -> dict:
    return {(r, c): S_MONEY
            for r in range(first_data_row, len(rows))
            for c in cols
            if isinstance(rows[r][c], (int, float))}


def _sheet_totals(res: Result, tally: list[Invoice], gstr: list[Invoice]) -> dict:
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)
    not_in_tally = unclaimed.get("missing_invoice", [])
    not_in_2a = ineligible.get("not_filed", []) + ineligible.get("supplier_absent", [])
    other_ledgers = unclaimed.get("supplier_absent", [])
    conflicts = pan_conflicts(res, tally, gstr)
    return {
        "not_in_tally": not_in_tally,
        "not_in_2a": not_in_2a,
        "other_ledgers": other_ledgers,
        "mismatches": partial_mismatches(res),
        # ITC at stake on a GSTIN conflict is the 2A side: that is what
        # re-matches once the ledger is corrected.
        "conflict_value": sum(c[6] for c in conflicts),
        "conflict_count": len(conflicts),
        "matched_tax": sum(p.gstr.tax for p in res.pairs),
    }


def _build_summary(t: dict, days_left: int, matched_count: int) -> list[list]:
    def total(rows):
        return sum(i.tax for i in rows)

    return [
        ["Milan - Annual GST ITC Reconciliation", "", "", ""],
        ["", "", "", ""],
        ["Sheet", "Bills", "Value", "What to do"],
        ["Matched and confirmed", matched_count, rupees(t["matched_tax"]),
         "Already correct - no action"],
        ["Not in Tally", len(t["not_in_tally"]), rupees(total(t["not_in_tally"])),
         f"Claim before 30 Nov 2026 ({days_left} days left)"],
        ["Not in 2A", len(t["not_in_2a"]), rupees(total(t["not_in_2a"])),
         "Chase the supplier to file, or reverse with interest u/s 50"],
        ["Partial Mismatch - amounts/dates", len(t["mismatches"]), "",
         "Both bills shown side by side - confirm which is right"],
        ["Partial Mismatch - GST number", t["conflict_count"], rupees(t["conflict_value"]),
         "Same supplier, two registrations - correct the ledger in Tally"],
        ["Other Ledgers (FYI)", len(t["other_ledgers"]), rupees(total(t["other_ledgers"])),
         "Confirmed nominal - reconciled through separate ledgers"],
    ]


def write_workbook(path: str, tally: list[Invoice], gstr: list[Invoice], res: Result) -> None:
    from datetime import date

    t = _sheet_totals(res, tally, gstr)
    days_left = (ITC_DEADLINE - date.today()).days
    wb = Workbook()

    summary = _build_summary(t, days_left, len(res.pairs))
    wb.add_sheet("Summary", summary, freeze_rows=3,
                 col_widths={0: 34, 1: 10, 2: 18, 3: 58})

    # --- Sheet 2: in 2A, never booked -------------------------------------
    rows = [_LEDGER_COLS] + _ledger_rows(
        t["not_in_tally"],
        "In 2A; this supplier is already in your books, this bill is not",
        f"Claim before 30 Nov 2026 ({days_left} days left)")
    wb.add_sheet("Not in Tally", rows, freeze_rows=1,
                 autofilter_range=f"A1:K{len(rows)}", col_widths=_LEDGER_WIDTHS,
                 cell_styles=_money_styles(rows, [4, 5, 6, 7, 8]))

    # --- Sheet 3: in books, not on the portal ------------------------------
    rows = [_LEDGER_COLS] + _ledger_rows(
        t["not_in_2a"],
        "Claimed in Tally, supplier has not filed it in 2A",
        "Chase the supplier to file, or reverse with interest u/s 50")
    wb.add_sheet("Not in 2A", rows, freeze_rows=1,
                 autofilter_range=f"A1:K{len(rows)}", col_widths=_LEDGER_WIDTHS,
                 cell_styles=_money_styles(rows, [4, 5, 6, 7, 8]))

    # --- Sheet 4: both bills side by side ----------------------------------
    rows = [_PAIR_COLS]
    for p, reasons, d_taxable, d_tax, d_days in t["mismatches"]:
        rows.append([
            p.gstr.supplier, " + ".join(reasons),
            p.gstr.gstin, p.gstr.inv_no, p.gstr.inv_date.isoformat(), p.gstr.taxable, p.gstr.tax,
            p.tally.gstin, p.tally.inv_no, p.tally.inv_date.isoformat(), p.tally.taxable, p.tally.tax,
            d_taxable, d_tax, d_days,
        ])
    rows.extend(gstin_conflict_rows(res, tally, gstr))
    wb.add_sheet("Partial Mismatch", rows, freeze_rows=1,
                 autofilter_range=f"A1:O{len(rows)}", col_widths=_PAIR_WIDTHS,
                 cell_styles=_money_styles(rows, [5, 6, 10, 11, 12, 13]))

    # --- Sheet 5: confirmed out of scope -----------------------------------
    rows = [_LEDGER_COLS] + _ledger_rows(
        t["other_ledgers"],
        "Supplier never appears in the purchase register",
        "Confirmed nominal - reconciled through separate ledgers")
    wb.add_sheet("Other Ledgers (FYI)", rows, freeze_rows=1,
                 autofilter_range=f"A1:K{len(rows)}", col_widths=_LEDGER_WIDTHS,
                 cell_styles=_money_styles(rows, [4, 5, 6, 7, 8]))

    wb.write(path)
