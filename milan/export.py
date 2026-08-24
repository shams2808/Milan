"""Write the findings as a CSV a practitioner can actually work in.

The terminal report is for reading. This is for doing: one row per finding,
with the bucket and the required action as ordinary columns, so it sorts and
filters in Excel the way every other working file in a tax practice does.

Deliberately one flat file rather than a workbook of sheets -- a flat table
can be filtered, pivoted and pasted into a client email; a multi-sheet
workbook cannot.
"""

from __future__ import annotations

import csv

from .core import Invoice, pan
from .match import AMOUNT, Result
from .report import classify_ineligible, classify_unclaimed

# bucket code -> (what it is, what to do about it)
ACTIONS = {
    "1a": ("In books, supplier has not filed it",
           "Chase supplier to file GSTR-1, or reverse the ITC with interest u/s 50"),
    "1b": ("In books against the wrong GST registration",
           "Same supplier PAN, different GSTIN. Correct the ledger in Tally and re-run"),
    "1c": ("In books, supplier absent from 2A entirely",
           "Supplier never filed, or is not registered. Verify the invoice is genuine"),
    "2a": ("In 2A, never booked",
           "Genuinely unclaimed ITC. Book it and claim before 30 Nov"),
    "2b": ("In 2A under the supplier's other registration",
           "Almost certainly already booked against a different GSTIN. Verify, then correct"),
    "2c": ("In 2A, supplier not in the purchase register",
           "Likely an expense booked outside Purchase vouchers. Verify before claiming"),
    "amt": ("Matched, but the tax differs",
            "Check which side is right; correct the books or raise it with the supplier"),
}

_FIELDS = [
    "bucket", "finding", "action", "side", "gstin", "pan", "supplier",
    "invoice_no", "invoice_date", "taxable", "igst", "cgst", "sgst", "cess",
    "tax", "counterpart_gstin", "counterpart_tax", "tax_difference",
]


def _row(bucket: str, side: str, inv: Invoice, **extra) -> dict:
    finding, action = ACTIONS[bucket]
    row = {
        "bucket": bucket,
        "finding": finding,
        "action": action,
        "side": side,
        "gstin": inv.gstin,
        "pan": pan(inv.gstin),
        "supplier": inv.supplier,
        "invoice_no": inv.inv_no,
        "invoice_date": inv.inv_date.isoformat(),
        "taxable": f"{inv.taxable:.2f}",
        "igst": f"{inv.igst:.2f}",
        "cgst": f"{inv.cgst:.2f}",
        "sgst": f"{inv.sgst:.2f}",
        "cess": f"{inv.cess:.2f}",
        "tax": f"{inv.tax:.2f}",
        "counterpart_gstin": "",
        "counterpart_tax": "",
        "tax_difference": "",
    }
    row.update(extra)
    return row


def write_csv(path: str, tally: list[Invoice], gstr: list[Invoice], res: Result) -> int:
    """Every finding, one row each. Returns the number of rows written.

    Matched invoices are NOT included -- they need no action, and 1,876 rows of
    'this was fine' would bury the 93 that are not.
    """
    ineligible = classify_ineligible(res, gstr)
    unclaimed = classify_unclaimed(res, tally)

    rows: list[dict] = []
    for inv in ineligible.get("not_filed", []):
        rows.append(_row("1a", "TALLY", inv))
    for inv in ineligible.get("other_registration", []):
        rows.append(_row("1b", "TALLY", inv))
    for inv in ineligible.get("supplier_absent", []):
        rows.append(_row("1c", "TALLY", inv))
    for inv in unclaimed.get("missing_invoice", []):
        rows.append(_row("2a", "2A", inv))
    for inv in unclaimed.get("other_registration", []):
        rows.append(_row("2b", "2A", inv))
    for inv in unclaimed.get("supplier_absent", []):
        rows.append(_row("2c", "2A", inv))

    for p in res.pairs:
        if p.stage == AMOUNT:
            rows.append(_row("amt", "TALLY", p.tally,
                             counterpart_gstin=p.gstr.gstin,
                             counterpart_tax=f"{p.gstr.tax:.2f}",
                             tax_difference=f"{p.tax_delta:.2f}"))

    # Biggest money first: that is the order the work gets done in.
    rows.sort(key=lambda r: (r["bucket"], -float(r["tax"])))

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)
