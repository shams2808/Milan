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
from .core import (
    FY_MONTHS,
    GSTR3BSummary,
    Invoice,
    MonthPosition,
    NUM_TO_MONTH,
    ThreeWayPosition,
    indian_number_format,
    pan,
    rupees,
)
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
    """Split 'in 2A, not in Tally' by WHY it is not in Tally.

    Credit notes are separated first and never mixed with invoices. A credit
    note carries NEGATIVE tax: the supplier reduced the supply. An unrecorded
    one therefore means the exact opposite of unclaimed credit -- the client is
    still claiming ITC the supplier has already withdrawn, so it is a liability,
    not an opportunity.

    Summing them together inverts the sign and destroys both findings: on the
    real client, 112 unrecorded credit notes worth -Rs 37.9L cancelled 109
    genuinely unclaimed invoices worth +Rs 6.5L and reported the total as
    "-Rs 31.4L of unclaimed ITC", which is not a number that can exist.
    See INCIDENTS.md #10.
    """
    tally_gstins = {t.gstin for t in tally}
    tally_pans = {pan(t.gstin) for t in tally}
    matched_gstins = {p.gstr.gstin for p in res.pairs}

    out: dict[str, list[Invoice]] = defaultdict(list)
    for g in res.only_gstr:
        if g.source == "2A_CDNR":
            out["unrecorded_credit_note"].append(g)
        elif g.gstin not in tally_gstins and pan(g.gstin) in tally_pans:
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


def print_report(
    tally: list[Invoice],
    gstr: list[Invoice],
    res: Result,
    *,
    show: int = 5,
    gstr3b: GSTR3BSummary | None = None,
) -> None:
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
            d_sign = "+" if p.tax_delta >= 0 else ""
            print(f"    {p.tally.gstin}  {p.tally.inv_no:<20} "
                  f"books {indian_number_format(p.tally.tax, 2):>12}   2A {indian_number_format(p.gstr.tax, 2):>12}   "
                  f"delta {d_sign + indian_number_format(p.tax_delta, 2):>12}")

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
    if gstr3b is not None:
        twp = compute_three_way_position(tally, gstr, res, gstr3b)
        print(f"  Matched but never claimed (in 3B) {rupees(twp.matched_unclaimed):>14}")
        print_three_way_report(twp, gstr3b)


def compute_three_way_position(
    tally: list[Invoice],
    gstr2a: list[Invoice],
    res: Result,
    gstr3b: GSTR3BSummary,
) -> ThreeWayPosition:
    """Three-way ITC position across GSTR-2A, Tally Books, and GSTR-3B.

    Reconciles Available (2A) -> Booked (Tally) -> Matched -> Claimed (3B),
    and computes month-by-month timing schedules.
    """
    def _month_of_date(d):
        return NUM_TO_MONTH.get(d.month, "April")

    def _month_of_fp(fp: str, default_date):
        if not fp:
            return _month_of_date(default_date)
        fp_clean = fp.strip()
        if len(fp_clean) == 6 and fp_clean.isdigit():
            m_num = int(fp_clean[:2])
            return NUM_TO_MONTH.get(m_num, _month_of_date(default_date))
        for m in FY_MONTHS:
            if fp_clean.lower().startswith(m[:3].lower()):
                return m
        return _month_of_date(default_date)

    g2a_by_date: dict[str, float] = defaultdict(float)
    g2a_by_fp: dict[str, float] = defaultdict(float)
    tally_by_date: dict[str, float] = defaultdict(float)

    b2b_gstr = [i for i in gstr2a if not i.source.endswith("CDNR")]
    for inv in b2b_gstr:
        m_d = _month_of_date(inv.inv_date)
        m_fp = _month_of_fp(inv.filing_period, inv.inv_date)
        g2a_by_date[m_d] += inv.tax
        g2a_by_fp[m_fp] += inv.tax

    for inv in tally:
        m_d = _month_of_date(inv.inv_date)
        tally_by_date[m_d] += inv.tax

    monthly_positions: list[MonthPosition] = []
    for m in FY_MONTHS:
        c_2a_d = round(g2a_by_date[m], 2)
        c_2a_fp = round(g2a_by_fp[m], 2)
        c_tally = round(tally_by_date[m], 2)
        m_3b = gstr3b.months.get(m)
        c_3b = round(m_3b.itc_non_rev if m_3b else 0.0, 2)
        var = round(c_3b - c_2a_fp, 2)
        monthly_positions.append(MonthPosition(
            month=m,
            tax_2a_by_invoice_date=c_2a_d,
            tax_2a_by_filing_period=c_2a_fp,
            tally_tax=c_tally,
            gstr3b_claimed=c_3b,
            variance_3b_2a=var,
        ))

    available_2a = round(sum(i.tax for i in b2b_gstr), 2)
    booked_tally = round(sum(i.tax for i in tally), 2)
    matched_tax = round(sum(p.gstr.tax for p in res.pairs), 2)
    claimed_3b = round(gstr3b.total_itc_non_rev, 2)

    return ThreeWayPosition(
        available_2a=available_2a,
        booked_tally=booked_tally,
        matched_tax=matched_tax,
        claimed_3b=claimed_3b,
        matched_unclaimed=round(matched_tax - claimed_3b, 2),
        gap_2a_3b=round(available_2a - claimed_3b, 2),
        only_tally_tax=round(sum(i.tax for i in res.only_tally), 2),
        only_2a_tax=round(sum(i.tax for i in res.only_gstr), 2),
        monthly=monthly_positions,
    )


def print_three_way_report(pos: ThreeWayPosition, gstr3b: GSTR3BSummary | None = None) -> None:
    print(f"\n{'=' * 78}")
    print("THREE-WAY ITC POSITION (TABLE 8 SHAPE)")
    print(f"{'=' * 78}")
    print(f"  GSTR-2A Available (Table 8A)      {rupees(pos.available_2a):>14}")
    print(f"  Tally Inward Booked               {rupees(pos.booked_tally):>14}")
    print(f"  Matched ITC Confirmed             {rupees(pos.matched_tax):>14}")
    print(f"  GSTR-3B Claimed (Table 4A)        {rupees(pos.claimed_3b):>14}")
    print(f"  {'-' * 76}")
    print(f"  MATCHED BUT NEVER CLAIMED         {rupees(pos.matched_unclaimed):>14}")
    print(f"  GSTR-2A vs GSTR-3B Total Gap       {rupees(pos.gap_2a_3b):>14}")
    print(f"{'=' * 78}")
    print("ANALYSIS OF GAPS")
    print(f"{'=' * 78}")
    print(f"  * Matched but never claimed: {rupees(pos.matched_unclaimed)}")
    print("    Invoices verified in both Tally and GSTR-2A where ITC was eligible,")
    print("    but total credit claimed in GSTR-3B monthly returns was lower.")
    print(f"  * In Tally, not in 2A: {rupees(pos.only_tally_tax)}")
    print("    Invoices booked in Tally but missing from GSTR-2A (supplier unfiled,")
    print("    wrong GSTIN, or late filing in subsequent financial year).")
    print(f"  * In 2A, not in Tally: {rupees(pos.only_2a_tax)}")
    print("    Available portal credits never booked in purchase register.")
    print()
    print("HONESTY CAVEAT ON GSTR-2A vs GSTR-3B GAP:")
    print(f"  GSTR-3B Table 4A includes imports, ISD, and reverse-charge credits that")
    print(f"  never appear in GSTR-2A B2B section. This summary does not break those")
    print(f"  out, so part of the {rupees(pos.gap_2a_3b)} gap is legitimately unreconcilable")
    print(f"  from these files alone.")
    print(f"\n{'=' * 78}")
    print("MONTH-BY-MONTH TIMING SCHEDULE")
    print(f"{'=' * 78}")
    print(f"{'Month':<10} | {'2A (Inv Date)':>14} | {'2A (Filing Mo)':>14} | {'Tally Booked':>14} | {'3B Claimed':>14} | {'Timing Diff':>14}")
    print("-" * 83)
    for mp in pos.monthly:
        d_str = ("+" if mp.variance_3b_2a >= 0 else "") + indian_number_format(mp.variance_3b_2a, 2)
        print(f"{mp.month:<10} | {indian_number_format(mp.tax_2a_by_invoice_date, 2):>14} | {indian_number_format(mp.tax_2a_by_filing_period, 2):>14} | {indian_number_format(mp.tally_tax, 2):>14} | {indian_number_format(mp.gstr3b_claimed, 2):>14} | {d_str:>14}")


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
