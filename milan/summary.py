"""The bill-level document behind the four-bucket plain-language summary.

report.py answers "how much, and why." This answers "which exact bills" --
the thing a practitioner actually needs to go act on a claim rather than just
trust a total. Every table here is invoice-level for the three buckets small
enough to read in full; the fourth (out-of-scope expenses, hundreds of rows)
is rolled up by supplier, with the CSV as the place to see every row.
"""

from __future__ import annotations

from .core import Invoice, rupees
from .match import Result
from .report import classify_ineligible, classify_unclaimed


def _bill_table(rows: list[Invoice]) -> str:
    rows = sorted(rows, key=lambda r: -r.tax)
    lines = ["| Supplier | GSTIN | Invoice No. | Date | Amount |",
             "|---|---|---|---|---:|"]
    for r in rows:
        lines.append(
            f"| {r.supplier or '(no name on file)'} | {r.gstin} | "
            f"{r.inv_no or '(blank)'} | {r.inv_date.isoformat()} | {rupees(r.tax)} |"
        )
    return "\n".join(lines)


def _supplier_rollup(rows: list[Invoice], *, limit: int | None = None) -> str:
    agg: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        agg.setdefault((r.gstin, r.supplier), []).append(r.tax)
    out = sorted(((g, n, len(v), sum(v)) for (g, n), v in agg.items()), key=lambda x: -x[3])
    if limit:
        out = out[:limit]
    lines = ["| Supplier | GSTIN | Bills | Total |",
             "|---|---|---:|---:|"]
    for g, n, c, t in out:
        lines.append(f"| {n or '(no name on file)'} | {g} | {c} | {rupees(t)} |")
    return "\n".join(lines)


def write_bill_summary(path: str, tally: list[Invoice], gstr: list[Invoice], res: Result) -> None:
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)

    claim_now = unclaimed.get("missing_invoice", [])
    chase = ineligible.get("not_filed", [])
    out_of_scope = unclaimed.get("supplier_absent", [])

    # "Fix ledger" (same supplier, wrong GST registration) is naturally a
    # per-supplier conflict, not a flat invoice list -- the two sides don't
    # correspond row-for-row, they correspond PAN-for-PAN. See core.pan().
    from .report import pan_conflicts
    conflicts = pan_conflicts(res, tally, gstr)

    parts = [
        "# Heamons -- GST ITC Reconciliation, Bill by Bill (FY 2025-26)",
        "",
        "**Confidential client data. For internal review only.**",
        "",
        "Backs the four-bucket summary with the actual invoices in each one. "
        "Sorted largest first within each table.",
        "",
        "---",
        "",
        f"## 1. Claim before 30 November 2026 -- {rupees(sum(r.tax for r in claim_now))}, "
        f"{len(claim_now)} bills",
        "",
        "In GSTR-2A, never booked in Tally. The supplier reported selling this to "
        "Heamons; nobody entered it in the books. This is the credit that expires.",
        "",
        _bill_table(claim_now),
        "",
        "---",
        "",
        f"## 2. Chase the supplier, or reverse the credit -- {rupees(sum(r.tax for r in chase))}, "
        f"{len(chase)} bills",
        "",
        "Claimed in Tally, but the supplier has not filed it in GSTR-2A. Until they "
        "do, this ITC is not legally available -- interest accrues under s.50 if it "
        "stays claimed without being reversed.",
        "",
        _bill_table(chase),
        "",
        "---",
        "",
        f"## 3. Fix the ledger, then re-run -- {rupees(sum(c[6] for c in conflicts))}, "
        f"{len(conflicts)} suppliers",
        "",
        "Same supplier (same PAN), booked in Tally under one GST registration while "
        "the portal shows it under a different one for that supplier. Not lost money "
        "-- correct the GSTIN in Tally and it reconciles. The ITC-at-stake amount is "
        "the 2A side, since that is what re-matches once the ledger is fixed.",
        "",
        "| Supplier PAN | Booked in Tally as | Shown in 2A as | Bills (2A) | ITC at stake |",
        "|---|---|---|---:|---:|",
    ]
    for pn, bg, pg, bn, bv, pcount, pv in conflicts:
        parts.append(
            f"| {pn} | {'/'.join(bg) or '-'} | {'/'.join(pg) or '-'} | {pcount} | {rupees(pv)} |"
        )

    parts += [
        "",
        "---",
        "",
        f"## 4. Out of scope (confirmed nominal, tracked elsewhere) -- "
        f"{rupees(sum(r.tax for r in out_of_scope))}, {len(out_of_scope)} bills across "
        f"{len({r.gstin for r in out_of_scope})} suppliers",
        "",
        "In GSTR-2A, but the supplier never appears in the Tally Purchase Register at "
        "all. Confirmed: bank charges, insurance, courier and platform fees booked "
        "through other ledgers, not missing money. Rolled up by supplier below -- "
        "every individual bill is in the CSV if any one of these needs a closer look.",
        "",
        _supplier_rollup(out_of_scope),
        "",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
