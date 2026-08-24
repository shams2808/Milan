"""Milan -- annual GST ITC reconciliation.

    python -m milan.run              # full synthetic year
    python -m milan.run --n 300

Reports the two piles a tax practitioner actually needs at year end:
    in Tally, not in 2A  ->  ITC claimed that was never available (reverse it)
    in 2A, not in Tally  ->  ITC available the client never claimed (expires)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date

from .core import Invoice, rupees
from .match import AMOUNT, EXACT, Result, reconcile
from .synth import build_year

# Section 16(4): ITC for a financial year lapses on 30 November of the year
# that follows it. After this date the money is simply gone.
ITC_DEADLINE = date(2026, 11, 30)


def _by_supplier(rows: list[Invoice]) -> list[tuple[str, str, int, float]]:
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        agg[(r.gstin, r.supplier)].append(r.tax)
    out = [(g, n, len(v), sum(v)) for (g, n), v in agg.items()]
    return sorted(out, key=lambda x: -x[3])


def suspected_gstin_typos(res: Result) -> list[tuple[Invoice, Invoice]]:
    """A mistyped GSTIN in Tally breaks the blocking key, so the same invoice
    lands in BOTH piles -- looking like an unclaimed credit and an ineligible
    claim at once. We do not auto-match these: the practitioner's rule is that
    the GST number must be the same. We surface them as a books correction.
    """
    out = []
    index: dict[tuple[str, float], list[Invoice]] = defaultdict(list)
    for g in res.only_gstr:
        index[(g.strict, round(g.tax, 2))].append(g)
    for t in res.only_tally:
        for cand in index.get((t.strict, round(t.tax, 2)), []):
            diff = sum(1 for a, b in zip(t.gstin, cand.gstin) if a != b)
            if len(t.gstin) == len(cand.gstin) and 0 < diff <= 2:
                out.append((t, cand))
                break
    return out


def evaluate(res: Result, planted: dict) -> dict:
    """Measured accuracy against ground truth. A pair is correct only if both
    sides carry the same truth_id."""
    correct = sum(1 for p in res.pairs if p.tally.truth_id == p.gstr.truth_id)
    total = len(res.pairs)
    return dict(
        correct=correct,
        wrong=total - correct,
        precision=correct / total if total else 0.0,
        recall=correct / planted["pairs"] if planted["pairs"] else 0.0,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--show", type=int, default=5, help="rows per section")
    args = ap.parse_args()

    tally, gstr, planted = build_year(n_invoices=args.n, seed=args.seed)
    res = reconcile(tally, gstr)

    print(f"\nMilan -- FY 2025-26 ITC reconciliation")
    print(f"Tally purchase register : {len(tally):>5} rows")
    print(f"GSTR-2A                 : {len(gstr):>5} rows")

    stages: dict[str, int] = defaultdict(int)
    for p in res.pairs:
        stages[p.stage] += 1

    matched_tax = sum(p.gstr.tax for p in res.pairs if p.stage != AMOUNT)
    print(f"\nmatched                 : {res.matched:>5} invoices   "
          f"{rupees(matched_tax)} ITC confirmed")
    for s, c in sorted(stages.items(), key=lambda x: -x[1]):
        print(f"    {s:<18}{c:>6}")
    print(f"    {'needs review':<18}{len(res.review):>6}")

    # --- the two piles ------------------------------------------------------
    claimed = sum(t.tax for t in res.only_tally)
    unclaimed = sum(g.tax for g in res.only_gstr)
    days = (ITC_DEADLINE - date.today()).days

    print(f"\n{'=' * 74}")
    print(f"PILE 1  in Tally, not in 2A -- ITC claimed that was never available")
    print(f"{'=' * 74}")
    print(f"  {len(res.only_tally)} invoices   {rupees(claimed)} at risk of reversal + interest u/s 50")
    for g, n, c, t in _by_supplier(res.only_tally)[: args.show]:
        print(f"    {g}  {n[:34]:<34} {c:>3} inv  {rupees(t):>14}")
    if len(_by_supplier(res.only_tally)) > args.show:
        print(f"    ... {len(_by_supplier(res.only_tally)) - args.show} more suppliers")

    print(f"\n{'=' * 74}")
    print(f"PILE 2  in 2A, not in Tally -- ITC available that was never claimed")
    print(f"{'=' * 74}")
    print(f"  {len(res.only_gstr)} invoices   {rupees(unclaimed)} claimable")
    print(f"  deadline 30 Nov 2026 (s.16(4)) -- {days} days left, then it lapses")
    for g, n, c, t in _by_supplier(res.only_gstr)[: args.show]:
        print(f"    {g}  {n[:34]:<34} {c:>3} inv  {rupees(t):>14}")

    # --- findings that are not simply "missing" -----------------------------
    amt = [p for p in res.pairs if p.stage == AMOUNT]
    if amt:
        net = sum(p.tax_delta for p in amt)
        print(f"\nAMOUNT MISMATCH  {len(amt)} invoices matched but tax differs, net {rupees(net)}")
        for p in sorted(amt, key=lambda p: -abs(p.tax_delta))[: args.show]:
            print(f"    {p.tally.gstin}  {p.tally.inv_no:<20} "
                  f"books {p.tally.tax:>10,.2f}   2A {p.gstr.tax:>10,.2f}   "
                  f"delta {p.tax_delta:>+10,.2f}")

    typos = suspected_gstin_typos(res)
    if typos:
        lost = sum(t.tax for t, _ in typos)
        print(f"\nSUSPECTED GSTIN TYPO IN BOOKS  {len(typos)} invoices, {rupees(lost)}")
        print("    same invoice number and tax on both sides, GSTIN differs by 1-2 characters.")
        print("    Not auto-matched -- the GST number must be identical. Fix in Tally, then rerun.")
        for t, g in typos[: args.show]:
            print(f"    books {t.gstin}  ->  2A {g.gstin}   {t.inv_no}   {rupees(t.tax)}")

    if res.dupes_tally:
        n = sum(len(d) - 1 for d in res.dupes_tally)
        v = sum(d[0].tax * (len(d) - 1) for d in res.dupes_tally)
        print(f"\nDUPLICATE IN BOOKS  {n} extra rows, {rupees(v)} double-counted")

    if res.review:
        print(f"\nREVIEW QUEUE  {len(res.review)} invoices the cascade refused to guess on")
        for t, cands, why in res.review[: args.show]:
            print(f"    {t.gstin}  {t.inv_no:<20} {why}")

    # --- measured accuracy --------------------------------------------------
    ev = evaluate(res, planted)
    print(f"\n{'-' * 74}")
    print("measured accuracy against ground truth (synthetic year)")
    print(f"  precision {ev['precision']:.3%}   recall {ev['recall']:.3%}   "
          f"wrong matches {ev['wrong']}")
    print(f"  planted: {planted}")
    print("\nReal files from a practising advocate land 1 Sept. These numbers are")
    print("from synthetic data and will move when they do.\n")


if __name__ == "__main__":
    main()
