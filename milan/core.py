"""Core records and invoice-number normalisation.

The whole reconciliation turns on one question: are these two rows the same
invoice? A practising tax advocate gave us the hard rule -- "GST number should
be same" -- so GSTIN is an exact blocking key and we never match across
suppliers. Everything hard happens *within* one supplier, where the two sides
spell the invoice number differently:

    GSTR-2A:  INV/2024-25/0001      Tally:  INV-24-25-1
    GSTR-2A:  0001                  Tally:  1
    GSTR-2A:  RIL/APR/117           Tally:  117

Normalisation is deliberately two-tier. `norm_strict` only does things that
cannot lose information. `norm_loose` strips financial-year fragments and
document-type prefixes, which is usually right but occasionally destroys a
real invoice number (a supplier whose invoice numbers genuinely look like
"2024"). Matching tries strict first, so loose can never override a confident
answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# Tolerance on total tax when deciding two rows are the same invoice.
# Confirmed with the practitioner directly: Rs 1, not a guess.
TAX_TOLERANCE = 1.0

# How far apart invoice dates may be and still be considered the same invoice.
# Books often carry the goods-receipt date rather than the invoice date.
DATE_TOLERANCE_DAYS = 7

# A token that could be half of a financial-year marker: 25, 26, 2025, 2026.
_YEARISH = re.compile(r"(?:20)?\d{2}")
# Leading letters on a token that carries digits: GST00006 -> 00006
_ALPHA_THEN_DIGITS = re.compile(r"([A-Z]+)(\d.*)")
_NONALNUM = re.compile(r"[^A-Z0-9]")
_SPLIT = re.compile(r"[^A-Z0-9]+")
# Document-type words that carry no identity.
_NOISE = {"INV", "INVOICE", "BILL", "BL", "GST", "TAX", "NO", "NUM", "SL", "SR",
          "DOC", "NUMBER", "SLNO", "SRNO"}


def norm_strict(s: str) -> str:
    """Uppercase, drop punctuation, drop leading zeros. Loses nothing."""
    s = _NONALNUM.sub("", (s or "").upper())
    return s.lstrip("0") or "0"


def norm_loose(s: str) -> str:
    """Strip financial-year markers and document-type prefixes.

    Token-based, NOT a regex over the raw string. An earlier version used
    `(?:20)?\d{2}[-/](?:20)?\d{2}` directly and matched "06/25" *inside*
    "006/25-26", so 006, 029 and 003 all collapsed onto "26" -- three distinct
    invoices sharing one key. Splitting into tokens first makes a year marker
    only removable when it is a whole token.
    """
    raw = (s or "").upper()
    toks = [t for t in _SPLIT.split(raw) if t]

    # A financial year appears as two adjacent year-ish tokens: 25|26, 2025|26.
    kept, i = [], 0
    while i < len(toks):
        if (i + 1 < len(toks)
                and _YEARISH.fullmatch(toks[i])
                and _YEARISH.fullmatch(toks[i + 1])):
            i += 2
            continue
        kept.append(toks[i])
        i += 1

    cleaned = []
    for t in kept:
        m = _ALPHA_THEN_DIGITS.fullmatch(t)
        if m:
            cleaned.append(m.group(2) if m.group(1) in _NOISE else t)
        elif t not in _NOISE:
            cleaned.append(t)

    if not cleaned:                       # stripped everything -- keep identity
        return norm_strict(raw)
    return "".join(cleaned).lstrip("0") or "0"


@dataclass
class Invoice:
    """One row from either side, normalised into a common shape."""

    gstin: str
    supplier: str
    inv_no: str
    inv_date: date
    taxable: float
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0
    period: str = ""          # return period it landed in, e.g. "2024-05"
    voucher_type: str = ""    # Tally side only: Purchase / Journal / Payment
    source: str = ""          # "2A" or "TALLY"
    row_id: str = ""
    truth_id: str = ""        # synthetic ground truth only; never read by matcher
    raw: dict = field(default_factory=dict)

    @property
    def tax(self) -> float:
        return round(self.igst + self.cgst + self.sgst + self.cess, 2)

    @property
    def total(self) -> float:
        return round(self.taxable + self.tax, 2)

    @property
    def strict(self) -> str:
        return norm_strict(self.inv_no)

    @property
    def loose(self) -> str:
        return norm_loose(self.inv_no)

    def __repr__(self) -> str:
        return f"<{self.source} {self.gstin} {self.inv_no!r} {self.inv_date} tax={self.tax}>"


def tax_close(a: Invoice, b: Invoice, tol: float = TAX_TOLERANCE) -> bool:
    return abs(a.tax - b.tax) <= tol


def date_close(a: Invoice, b: Invoice, days: int = DATE_TOLERANCE_DAYS) -> bool:
    return abs((a.inv_date - b.inv_date).days) <= days


def pan(gstin: str) -> str:
    """A GSTIN is 2 state digits + 10-char PAN + 3. Two GSTINs sharing a PAN
    are the SAME legal entity registered in different states -- Ingram Micro
    bills from 27 (Maharashtra) and 06 (Haryana) with one PAN. Those are
    legally distinct registrations, so we never match across them; we report
    the conflict so the books can be corrected."""
    return gstin[2:12] if len(gstin) >= 12 else gstin


def rupees(x: float) -> str:
    return f"Rs {x:,.0f}"
