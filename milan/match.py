"""GSTIN-blocked matching cascade.

Every stage is deterministic and runs strongest-first, so a weaker rule can
never overturn a confident answer. Ambiguity is never resolved by guessing:
if two candidates fit equally well, the pair goes to the review queue with
both candidates attached. That queue is what the LLM tail will read (it gets
the residual plus its candidates and must pick one or abstain) -- it is not
allowed to invent a match the cascade never proposed.

No LLM runs here. Matching an invoice wrong moves a real ITC claim.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from .core import Invoice, date_close, tax_close

def _edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein: an adjacent transposition costs 1, not 2.

    Two earlier versions of this were wrong. difflib's ratio is worthless on
    strings this short ("12" vs "21" scores 0.5), and plain Levenshtein scores
    a transposition as 2 because it needs a delete plus an insert -- so the
    single most common typing error scored the same as an unrelated number.
    See INCIDENTS.md #3.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 99
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


_LEADING_ALPHA = re.compile(r"^([A-Z]+)(\d.*)$")


def _is_coded(short: str, long: str) -> bool:
    """`long` is `short` with the supplier's own alphabetic code bolted on:
    2A writes "SEL/0012", the books write "12". The numeric remainder must
    match once its leading zeros are gone -- comparing the raw strings failed
    because the prefix "SEL00" is not alphabetic."""
    m = _LEADING_ALPHA.fullmatch(long)
    if not m or not short:
        return False
    return (m.group(2).lstrip("0") or "0") == short

# Two rows carrying the same invoice number but dated months apart are not the
# same document, however well the number matches. Suppliers restart numbering,
# and recurring billers repeat amounts. Beyond this gap we refuse to assert a
# match and send the pair to review instead. See INCIDENTS.md #2.
MAX_MATCH_GAP_DAYS = 90


def _usable(inv) -> bool:
    """Does this row carry an invoice number that can identify anything?
    Blank cells and bare zeros come from bulk journal entries."""
    return len(inv.strict) > 1 or inv.strict not in ("", "0")

# Stages, strongest first. The label is what the advocate reads in the report.
EXACT = "exact"                    # same normalised number, same tax
FORMAT = "format_variant"          # same number once FY/prefix noise removed
AMOUNT = "amount_mismatch"         # same invoice, tax differs -> needs attention
TYPO = "typo_in_number"            # one character out; tax and date agree
CODED = "supplier_code"            # one side carries the supplier's own prefix
BYVALUE = "value_and_date"         # number unusable; unique tax+date candidate
AMBIGUOUS = "ambiguous"            # several equally good candidates -> review


@dataclass
class Pair:
    tally: Invoice
    gstr: Invoice
    stage: str
    note: str = ""

    @property
    def tax_delta(self) -> float:
        return round(self.tally.tax - self.gstr.tax, 2)


@dataclass
class Result:
    pairs: list[Pair]
    only_tally: list[Invoice]       # ITC claimed but never available
    only_gstr: list[Invoice]        # ITC available but never claimed
    review: list[tuple[Invoice, list[Invoice], str]]
    dupes_tally: list[list[Invoice]]
    dupes_gstr: list[list[Invoice]]

    @property
    def matched(self) -> int:
        return len(self.pairs)


def _find_dupes(rows: list[Invoice]) -> list[list[Invoice]]:
    """Same supplier, same normalised number, same tax, booked twice."""
    buckets: dict[tuple, list[Invoice]] = defaultdict(list)
    for r in rows:
        buckets[(r.gstin, r.strict, round(r.tax, 2))].append(r)
    return [v for v in buckets.values() if len(v) > 1]


def _consume(pairs, used_t, used_g, t, g, stage, note=""):
    pairs.append(Pair(t, g, stage, note))
    used_t.add(t.row_id)
    used_g.add(g.row_id)


def reconcile(tally: list[Invoice], gstr: list[Invoice]) -> Result:
    pairs: list[Pair] = []
    review: list[tuple[Invoice, list[Invoice], str]] = []
    used_t: set[str] = set()
    used_g: set[str] = set()

    by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    for g in gstr:
        by_gstin[g.gstin].append(g)

    def avail(gstin: str) -> list[Invoice]:
        return [g for g in by_gstin.get(gstin, []) if g.row_id not in used_g]

    def pass_over(predicate, stage, note=""):
        """One cascade stage. Unique candidate matches; several go to review."""
        for t in tally:
            if t.row_id in used_t:
                continue
            hits = [g for g in avail(t.gstin) if predicate(t, g)]
            if len(hits) == 1:
                _consume(pairs, used_t, used_g, t, hits[0], stage, note)
            elif len(hits) > 1:
                review.append((t, hits, f"{len(hits)} equally good candidates at stage '{stage}'"))
                used_t.add(t.row_id)

    def near_enough(t, g) -> bool:
        return date_close(t, g, MAX_MATCH_GAP_DAYS)

    # 1. Identical once punctuation and leading zeros are gone.
    pass_over(lambda t, g: t.strict == g.strict and tax_close(t, g) and near_enough(t, g),
              EXACT)

    # 2. Identical once financial-year and document-type noise is stripped.
    pass_over(lambda t, g: t.loose == g.loose and tax_close(t, g) and near_enough(t, g),
              FORMAT, "invoice number written differently on the two sides")

    # 3. Same invoice, different tax. A real finding, not a matching failure.
    #    Requires the dates to agree closely -- if the number matches but tax
    #    AND date both disagree, these are two different documents.
    pass_over(lambda t, g: t.loose == g.loose and not tax_close(t, g) and date_close(t, g),
              AMOUNT, "same invoice number, tax value differs")

    # 4a and 4b both compare one invoice number against another, so both
    # require an actual number on each side. A blank cell normalises to "0",
    # which sits one edit away from every single-character invoice number --
    # without this guard, blanks were claimed as typos of "6". A missing
    # number is not a typo, it is a missing number: that is stage 5's job.

    # 4a. One side carries a supplier code the other never recorded.
    pass_over(lambda t, g: _usable(t) and _usable(g)
              and tax_close(t, g) and date_close(t, g)
              and (_is_coded(t.loose, g.loose) or _is_coded(g.loose, t.loose)),
              CODED, "one side carries the supplier's own invoice prefix")

    # 4b. A single character out -- transposed or mistyped digit. Requires tax
    #     AND date to agree, so a near-miss number alone can never carry it.
    pass_over(lambda t, g: _usable(t) and _usable(g)
              and tax_close(t, g) and date_close(t, g)
              and _edit_distance(t.loose, g.loose) <= 1,
              TYPO, "invoice number differs by one character; tax and date agree")

    # 5. Invoice number is unusable on one side (bulk entry, blank cell).
    #    Only fires when a number is genuinely missing -- never to override two
    #    readable numbers that disagree, which is how recurring billers (same
    #    amount every month) produce confident false matches.
    pass_over(lambda t, g: tax_close(t, g) and date_close(t, g)
              and not (_usable(t) and _usable(g)),
              BYVALUE, "matched on tax and date; invoice number unusable")

    only_t = [t for t in tally if t.row_id not in used_t]
    only_g = [g for g in gstr if g.row_id not in used_g]

    return Result(
        pairs=pairs,
        only_tally=only_t,
        only_gstr=only_g,
        review=review,
        dupes_tally=_find_dupes(tally),
        dupes_gstr=_find_dupes(gstr),
    )
