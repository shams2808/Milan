"""Flagging credits that may be blocked under s.17(5) of the CGST Act.

WHAT THIS DOES AND DOES NOT DO
------------------------------
It flags. It never decides, and it never excludes anything from a total.
Whether a credit is blocked is a legal determination that depends on facts no
spreadsheet contains -- whether a repair was capitalised, whether insurance was
obligatory for the employer, whether a works contract fed a further works
contract. A tax advocate makes that call. This narrows 2,418 invoices down to
the handful worth his attention, with the clause and the reason attached.

WHY THE RULES COME FIRST
------------------------
A supplier named "JAIN TIMBER TRADERS" or "KOTAK MAHINDRA LIFE INSURANCE" is
not a judgement call, it is a lookup. Rules are exact, free, auditable, and
they carry most of the volume. The LLM exists for the residual where the
supplier name genuinely does not say what was bought -- and even there it must
return a clause and a confidence, or abstain.

The rules below are keyed to the actual clauses of s.17(5). Each carries the
statutory exception, because the exception is usually what decides the case and
the practitioner needs to see it to rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .core import Invoice


@dataclass
class Flag:
    clause: str
    label: str
    why: str
    exception: str
    confidence: float
    source: str = "rules"   # "rules" or "llm"


# clause -> (label, statutory exception, keyword patterns)
# Patterns match the supplier's trade name, which is all GSTR-2A gives us.
_RULES: list[tuple[str, str, str, str, list[str]]] = [
    (
        "17(5)(c)/(d)",
        "Construction / works contract",
        "goods or services for construction of immovable property on own account",
        "Allowed if it is plant & machinery, or an input to a further works contract.",
        [r"\bTIMBER\b", r"\bTILES?\b", r"\bSANITARY\b", r"\bCEMENT\b", r"\bMARBLE\b",
         r"\bGRANITE\b", r"\bPLYWOOD\b", r"\bHARDWARE\b", r"\bPAINTS?\b",
         r"\bCONSTRUCTION\b", r"\bBUILDERS?\b", r"\bINTERIOR", r"\bCIVIL WORK",
         r"\bBRICK", r"\bSTEEL\s*&?\s*CEMENT"],
    ),
    (
        "17(5)(b)(i)",
        "Life or health insurance",
        "life and health insurance are blocked",
        "Allowed only where the employer is obligated to provide it under law.",
        [r"\bLIFE INSURANCE\b", r"\bHEALTH INSURANCE\b", r"\bMEDICLAIM\b",
         r"\bLIFE INSUR", r"\bHEALTH INSUR"],
    ),
    (
        "17(5)(b)(i)",
        "Food, beverages, catering",
        "food and beverages and outdoor catering are blocked",
        "Allowed if used to make an outward taxable supply of the same category, "
        "or where obligatory for the employer.",
        [r"\bRESTAURANT\b", r"\bCATER", r"\bSWEETS?\b", r"\bBAKERY\b",
         r"\bFOODS?\b", r"\bHOTELS?\b", r"\bRESORTS?\b", r"\bCAFE\b",
         r"\bZOMATO\b", r"\bSWIGGY\b"],
    ),
    (
        "17(5)(b)(ii)",
        "Club or fitness membership",
        "membership of a club, health or fitness centre is blocked",
        "No general exception.",
        [r"\bCLUB\b", r"\bFITNESS\b", r"\bGYM\b", r"\bSPORTS CLUB\b"],
    ),
    (
        "17(5)(a)",
        "Motor vehicle",
        "motor vehicles for transport of persons (<=13 seats) are blocked",
        "Allowed for further supply of vehicles, passenger transport, or driving "
        "instruction.",
        [r"\bMOTORS?\b", r"\bAUTOMOBILES?\b", r"\bMARUTI\b", r"\bHYUNDAI\b",
         r"\bHONDA CARS?\b", r"\bTOYOTA\b", r"\bCAR\b"],
    ),
    (
        "17(5)(b)(i)",
        "Beauty, health or cosmetic services",
        "beauty treatment, health services and cosmetic surgery are blocked",
        "Allowed if used to make an outward taxable supply of the same category.",
        [r"\bSALON\b", r"\bSPA\b", r"\bBEAUTY\b", r"\bCLINIC\b", r"\bHOSPITAL\b",
         r"\bDIAGNOSTIC", r"\bPATHOLOG"],
    ),
]

_COMPILED = [(c, lab, why, exc, [re.compile(p, re.I) for p in pats])
             for c, lab, why, exc, pats in _RULES]

# Names that read like a blocked category but are ordinary business inputs.
# "Apollo Tyres" is not a hospital; "Bata" is not a restaurant.
_NOT_BLOCKED = re.compile(
    r"\bTYRES?\b|\bTUBES?\b|\bLOGISTIC|\bTRANSPORT|\bCOURIER|\bFREIGHT|"
    r"\bSOFTWARE\b|\bTECHNOLOG|\bINFOTECH\b|\bSYSTEMS?\b|\bSOLUTIONS?\b",
    re.I,
)


def flag_rules(inv: Invoice) -> Flag | None:
    """Deterministic pass. Returns a Flag or None. Never raises."""
    name = (inv.supplier or "").upper()
    if not name or _NOT_BLOCKED.search(name):
        return None
    for clause, label, why, exception, pats in _COMPILED:
        if any(p.search(name) for p in pats):
            return Flag(clause, label, why, exception, confidence=0.80)
    return None


def flag_all(invoices: list[Invoice]) -> dict[str, Flag]:
    """Flag a list of invoices by row_id. Rules only.

    The LLM tail (llm_flag below) is not wired into this path yet -- it needs an
    API key and a practitioner-reviewed prompt. Rules alone are already exact on
    the categories they cover, and a rule that fires is auditable in a way an
    LLM answer is not.
    """
    out: dict[str, Flag] = {}
    for inv in invoices:
        f = flag_rules(inv)
        if f:
            out[inv.row_id] = f
    return out


def unflagged_suppliers(invoices: list[Invoice], flags: dict[str, Flag]) -> list[tuple[str, int, float]]:
    """Suppliers the rules said nothing about, biggest first.

    This is the LLM's queue, and it is also the honest measure of how far the
    rules actually reach. A trade name like "Aadi Technologies" or "VINAY JAIN"
    does not say what was sold; that is exactly the residual an LLM should read
    with the invoice value and rate as context, returning a clause and a
    confidence or abstaining.
    """
    agg: dict[str, list[float]] = {}
    for inv in invoices:
        if inv.row_id in flags:
            continue
        agg.setdefault(inv.supplier or inv.gstin, []).append(inv.tax)
    return sorted(((k, len(v), sum(v)) for k, v in agg.items()), key=lambda x: -x[2])


LLM_PROMPT = """You classify Indian GST supplier invoices against s.17(5) CGST blocked credits.

Supplier trade name: {supplier}
Invoice value (taxable): Rs {taxable:,.2f}
Tax: Rs {tax:,.2f}

Reply with JSON only: {{"clause": "<s.17(5) clause or null>", "label": "<short>",
"confidence": <0.0-1.0>, "reason": "<one sentence>"}}

Rules you must follow:
- A trade name alone is often insufficient. If it does not clearly indicate what
  was supplied, return clause null with confidence 0.0. Abstaining is correct
  and expected; guessing costs a practitioner more time than it saves.
- Never assert a credit IS blocked. s.17(5) turns on facts not present here
  (whether a repair was capitalised, whether insurance was obligatory, whether a
  works contract fed another). You are proposing a review candidate, nothing more.
"""
