"""Turning a Result into the two piles a practitioner acts on.

The first real-data run reported "542 invoices in 2A but not in Tally" as one
flat number. It was wrong -- not arithmetically (every row is accounted for)
but *diagnostically*. Four completely different situations were being added
together, and only one of them is unclaimed ITC. See INCIDENTS.md #6.

An undifferentiated pile of 542 rows is exactly the output a practitioner
already gets from existing tools and then does by hand anyway. The value is
in splitting it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .blocked import flag_all, unflagged_suppliers
from .core import Invoice, pan, rupees
from .match import AMOUNT, Result

# Section 16(4): ITC for a financial year lapses on 30 November of the year
# that follows it. After this date the money is simply gone.
ITC_DEADLINE = date(2026, 11, 30)

# Below this tax value an inward supply is almost always an expense (bank
# charge, courier, platform fee) rather than a goods purchase. Used only to
# describe a bucket, never to match or exclude anything.
SMALL_TAX = 2000.0


def _by_supplier(rows: list[Invoice]) -> list[tuple[str, str, int, float]]:
    agg: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        agg[(r.gstin, r.supplier)].append(r.tax)
    out = [(g, n, len(v), sum(v)) for (g, n), v in agg.items()]
    return sorted(out, key=lambda x: -x[3])


def _total(rows) -> float:
    return sum(r.tax for r in rows)


def classify_unclaimed(res: Result, tally: list[Invoice]) -> dict[str, list[Invoice]]:
    """Split 'in 2A, not in Tally' by WHY it is not in Tally."""
    tally_gstins = {t.gstin for t in tally}
    tally_pans = {pan(t.gstin) for t in tally}
    matched_gstins = {p.gstr.gstin for p in res.pairs}

    out: dict[str, list[Invoice]] = defaultdict(list)
    for g in res.only_gstr:
        if g.gstin not in tally_gstins and pan(g.gstin) in tally_pans:
            out["other_registration"].append(g)
        elif g.gstin in matched_gstins or g.gstin in tally_gstins:
            out["missing_invoice"].append(g)
        else:
            out["supplier_absent"].append(g)
    return out


def classify_ineligible(res: Result, gstr: list[Invoice]) -> dict[str, list[Invoice]]:
    """Split 'in Tally, not in 2A' by WHY it is not in 2A."""
    gstr_gstins = {g.gstin for g in gstr}
    gstr_pans = {pan(g.gstin) for g in gstr}

    out: dict[str, list[Invoice]] = defaultdict(list)
    for t in res.only_tally:
        if t.gstin not in gstr_gstins and pan(t.gstin) in gstr_pans:
            out["other_registration"].append(t)
        elif t.gstin in gstr_gstins:
            out["not_filed"].append(t)
        else:
            out["supplier_absent"].append(t)
    return out


def pan_conflicts(res: Result, tally: list[Invoice], gstr: list[Invoice]) -> list[tuple]:
    """One row per PAN with unmatched invoices on both sides under different
    GSTINs. Returns (pan, books_gstins, portal_gstins, books_count, books_tax,
    portal_count, portal_tax).

    Groups the already-correct, already-deduplicated 'other_registration'
    invoices from classify_ineligible/classify_unclaimed by PAN -- it does not
    re-derive who is unmatched. An earlier version joined every books-GSTIN
    against every portal-GSTIN sharing a PAN directly, so a supplier filing
    from three registrations (Redington: two portal GSTINs against one books
    GSTIN) had its books invoices counted once per portal GSTIN they were
    compared against -- the same 4 invoices, Rs 15,418, appeared twice.
    Grouping instead of joining means each invoice is counted exactly once.
    """
    books_orr = classify_ineligible(res, gstr).get("other_registration", [])
    portal_orr = classify_unclaimed(res, tally).get("other_registration", [])

    def by_pan(rows: list[Invoice]) -> dict[str, list[Invoice]]:
        out: dict[str, list[Invoice]] = defaultdict(list)
        for r in rows:
            out[pan(r.gstin)].append(r)
        return out

    b, p = by_pan(books_orr), by_pan(portal_orr)
    out = []
    for k in set(b) | set(p):
        brows, prows = b.get(k, []), p.get(k, [])
        out.append((
            k,
            sorted({r.gstin for r in brows}),
            sorted({r.gstin for r in prows}),
            len(brows), _total(brows),
            len(prows), _total(prows),
        ))
    return sorted(out, key=lambda x: -x[6])


def evaluate(res: Result, planted: dict) -> dict:
    """Measured accuracy against ground truth. Only meaningful on synthetic
    data -- a pair is correct only if both sides carry the same truth_id,
    which real invoices never have."""
    correct = sum(1 for p in res.pairs if p.tally.truth_id == p.gstr.truth_id)
    total = len(res.pairs)
    return dict(
        correct=correct,
        wrong=total - correct,
        precision=correct / total if total else 0.0,
        recall=correct / planted["pairs"] if planted["pairs"] else 0.0,
    )


def _show_suppliers(rows: list[Invoice], show: int, indent: str = "      ") -> None:
    listed = _by_supplier(rows)
    for g, n, c, t in listed[:show]:
        print(f"{indent}{g}  {n[:34]:<34} {c:>3} inv  {rupees(t):>13}")
    if len(listed) > show:
        print(f"{indent}... {len(listed) - show} more suppliers")


def print_report(tally: list[Invoice], gstr: list[Invoice], res: Result, *, show: int = 5) -> None:
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

    days = (ITC_DEADLINE - date.today()).days
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)

    # --- PILE 1 -------------------------------------------------------------
    print(f"\n{'=' * 78}")
    print("PILE 1  in Tally, not in 2A")
    print(f"{'=' * 78}")
    print(f"  {len(res.only_tally)} invoices, {rupees(_total(res.only_tally))} total -- split by cause:\n")

    nf = ineligible.get("not_filed", [])
    print(f"  [1a] SUPPLIER HAS NOT FILED THIS INVOICE      {len(nf):>4} inv  {rupees(_total(nf)):>13}")
    print("       ITC claimed but not available. Chase the supplier, or reverse")
    print("       it with interest u/s 50.")
    _show_suppliers(nf, show)

    orr = ineligible.get("other_registration", [])
    if orr:
        print(f"\n  [1b] BOOKED AGAINST THE WRONG REGISTRATION    {len(orr):>4} inv  {rupees(_total(orr)):>13}")
        print("       Same supplier PAN, different GSTIN. Not missing -- fix the")
        print("       ledger in Tally and this reconciles.")
        _show_suppliers(orr, show)

    sa = ineligible.get("supplier_absent", [])
    if sa:
        print(f"\n  [1c] SUPPLIER NOWHERE IN 2A                   {len(sa):>4} inv  {rupees(_total(sa)):>13}")
        print("       Never filed at all, or not a registered supplier.")
        _show_suppliers(sa, show)

    # --- PILE 2 -------------------------------------------------------------
    print(f"\n{'=' * 78}")
    print("PILE 2  in 2A, not in Tally")
    print(f"{'=' * 78}")
    print(f"  {len(res.only_gstr)} invoices, {rupees(_total(res.only_gstr))} total -- but only part")
    print("  of this is genuinely unclaimed ITC:\n")

    mi = unclaimed.get("missing_invoice", [])
    print(f"  [2a] GENUINELY UNCLAIMED                      {len(mi):>4} inv  {rupees(_total(mi)):>13}")
    print(f"       You already buy from these suppliers, but these invoices were")
    print(f"       never booked. Claim before 30 Nov 2026 -- {days} days left.")
    _show_suppliers(mi, show)

    orr2 = unclaimed.get("other_registration", [])
    if orr2:
        print(f"\n  [2b] SUPPLIER'S OTHER REGISTRATION            {len(orr2):>4} inv  {rupees(_total(orr2)):>13}")
        print("       Same PAN as a supplier in your books, different GSTIN.")
        print("       Almost certainly already booked against the wrong ledger.")
        _show_suppliers(orr2, show)

    ab = unclaimed.get("supplier_absent", [])
    if ab:
        small = [g for g in ab if g.tax < SMALL_TAX]
        print(f"\n  [2c] SUPPLIER NOT IN THE PURCHASE REGISTER    {len(ab):>4} inv  {rupees(_total(ab)):>13}")
        print(f"       {len(small)} of these ({len(small) / len(ab):.0%}) are under {rupees(SMALL_TAX)} tax --")
        print("       consistent with the practitioner's read: nominal amounts, already")
        print("       reconciled through separate ledgers (bank charges, insurance,")
        print("       platform fees). OUT OF SCOPE for this tool by design, not a gap.")
        _show_suppliers(ab, show)

    # --- findings that are not simply "missing" -----------------------------
    amt = [p for p in res.pairs if p.stage == AMOUNT]
    if amt:
        net = sum(p.tax_delta for p in amt)
        print(f"\n{'=' * 78}")
        print(f"AMOUNT MISMATCH  {len(amt)} invoices matched but tax differs, net {rupees(net)}")
        for p in sorted(amt, key=lambda p: -abs(p.tax_delta))[:show]:
            print(f"    {p.tally.gstin}  {p.tally.inv_no:<20} "
                  f"books {p.tally.tax:>10,.2f}   2A {p.gstr.tax:>10,.2f}   "
                  f"delta {p.tax_delta:>+10,.2f}")

    conflicts = pan_conflicts(res, tally, gstr)
    if conflicts:
        total_v = sum(c[6] for c in conflicts)
        print(f"\nSAME SUPPLIER, TWO REGISTRATIONS  {len(conflicts)} suppliers, {rupees(total_v)}")
        print("    Not auto-matched: different GSTINs are different registrations.")
        for pn, bg, pg, bn, bv, pcount, pv in conflicts[:show]:
            print(f"    PAN {pn}   books {'/'.join(bg) or '-'} ({bn} inv, {rupees(bv)})"
                  f"  ->  2A {'/'.join(pg) or '-'} ({pcount} inv, {rupees(pv)})")

    # s.17(5) review candidates. Flagged, never excluded from any total --
    # whether a credit is blocked is a legal call the practitioner makes.
    flags = flag_all(tally + res.only_gstr)
    if flags:
        rows = [i for i in tally + res.only_gstr if i.row_id in flags]
        claimed = [i for i in rows if i.source == "TALLY"]
        print(f"\n{'=' * 78}")
        print(f"POSSIBLY BLOCKED UNDER s.17(5)   {len(rows)} invoices, {rupees(_total(rows))}")
        print(f"{'=' * 78}")
        if claimed:
            print(f"  {len(claimed)} of these are ALREADY CLAIMED ({rupees(_total(claimed))}) -- live exposure.")
        print("  Flagged for review, not excluded. s.17(5) turns on facts not in these")
        print("  files: whether a repair was capitalised, whether insurance was")
        print("  obligatory, whether a works contract fed another.")
        grouped: dict[str, list] = defaultdict(list)
        for i in rows:
            f = flags[i.row_id]
            grouped[f"{f.clause}  {f.label}"].append(i)
        for k, items in sorted(grouped.items(), key=lambda x: -_total(x[1])):
            f = flags[items[0].row_id]
            print(f"\n  {k}   {len(items)} inv  {rupees(_total(items))}")
            print(f"      exception: {f.exception}")
            _show_suppliers(items, 3, indent="      ")

    # Suppliers the rules could not classify at all -- not sent to an LLM.
    # The practitioner's instruction: no guessing here, a manual list to check.
    unclassified = unflagged_suppliers(mi, flags)
    if unclassified:
        print(f"\n{'=' * 78}")
        print(f"MANUAL REVIEW  {len(unclassified)} suppliers in [2a], trade name alone")
        print("does not say what was bought -- not run through s.17(5) rules, no AI guess")
        print(f"{'=' * 78}")
        for name, n, v in unclassified[:show]:
            print(f"      {name[:44]:<44} {n:>3} inv  {rupees(v):>13}")
        if len(unclassified) > show:
            print(f"      ... {len(unclassified) - show} more")

    if res.dupes_tally:
        n = sum(len(d) - 1 for d in res.dupes_tally)
        v = sum(d[0].tax * (len(d) - 1) for d in res.dupes_tally)
        print(f"\nDUPLICATE IN BOOKS  {n} extra rows, {rupees(v)} double-counted")

    if res.review:
        print(f"\nREVIEW QUEUE  {len(res.review)} invoices the cascade refused to guess on")
        for t, cands, why in res.review[:show]:
            print(f"    {t.gstin}  {t.inv_no:<20} {why}")

    # --- the one number that matters ----------------------------------------
    print(f"\n{'=' * 78}")
    print("BOTTOM LINE")
    print(f"{'=' * 78}")
    print(f"  ITC confirmed against 2A          {rupees(matched_tax):>14}")
    print(f"  Claim before 30 Nov ({days}d)        {rupees(_total(mi)):>14}   [2a]")
    print(f"  Reverse or chase supplier         {rupees(_total(nf)):>14}   [1a]")
    # NOT orr + orr2: those are the same invoices seen from each side, and
    # adding them double-counts the money. The portal side is the ITC at stake.
    print(f"  Fix ledger, then re-run           {rupees(_total(orr2)):>14}   [1b+2b, same invoices]")
    print(f"  Out of scope (confirmed nominal)  {rupees(_total(ab)):>14}   [2c, not counted above]")


def suspected_gstin_typos(res: Result) -> list[tuple[Invoice, Invoice]]:
    """Kept for the synthetic suite: a mistyped GSTIN puts the same invoice in
    both piles. On real data `pan_conflicts` is the stronger signal, because a
    supplier's second state registration differs in 3+ characters and this
    edit-distance check would miss it entirely."""
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
