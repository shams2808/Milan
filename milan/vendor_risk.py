"""Vendor Risk Classification & Invoice Management System (IMS) Directives.

Calculates compliance grades (A/B/C/D), trapped working capital per supplier,
and automated IMS accept/hold/reject directives.
Standard library only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from .core import Invoice, pan
from .match import AMOUNT, Result
from .report import classify_ineligible, classify_unclaimed, pan_conflicts


@dataclass
class VendorScorecard:
    gstin: str
    name: str
    pan: str
    booked_count: int
    booked_tax: float
    portal_count: int
    portal_tax: float
    matched_count: int
    matched_tax: float
    unfiled_count: int
    unfiled_tax: float
    unclaimed_count: int
    unclaimed_tax: float
    multi_state_conflict: bool
    compliance_rate: float  # 0% to 100%
    grade: str  # "A" (Compliant), "B" (Timing Lag), "C" (Delinquent), "D" (Multi-State PAN)
    ims_action: str  # "ACCEPT", "HOLD PENDING", "REJECT", "LEDGER FIX"
    ims_recommendation: str


@dataclass
class IMSAggregateSummary:
    total_vendors_analyzed: int
    grade_a_count: int
    grade_b_count: int
    grade_c_count: int
    grade_d_count: int
    ims_accept_tax: float
    ims_accept_count: int
    ims_pending_tax: float
    ims_pending_count: int
    ims_reject_tax: float
    ims_reject_count: int
    top_risk_vendors: list[VendorScorecard] = field(default_factory=list)


def evaluate_vendor_risk(
    tally: Sequence[Invoice],
    gstr: Sequence[Invoice],
    res: Result,
) -> tuple[list[VendorScorecard], IMSAggregateSummary]:
    """Compute comprehensive risk scorecards for all suppliers."""
    ineligible = classify_ineligible(res, gstr)
    unclaimed = classify_unclaimed(res, tally)
    conflicts = pan_conflicts(res, tally, gstr)
    conflict_pans = {c[0] for c in conflicts}

    # Index by GSTIN
    booked_by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    portal_by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    names_by_gstin: dict[str, str] = {}

    for i in tally:
        booked_by_gstin[i.gstin].append(i)
        if i.supplier and not names_by_gstin.get(i.gstin):
            names_by_gstin[i.gstin] = i.supplier

    for i in gstr:
        portal_by_gstin[i.gstin].append(i)
        if i.supplier and not names_by_gstin.get(i.gstin):
            names_by_gstin[i.gstin] = i.supplier

    # Matched pairs by GSTIN
    matched_by_gstin: dict[str, list] = defaultdict(list)
    for p in res.pairs:
        matched_by_gstin[p.tally.gstin].append(p)

    # Unfiled (in Books, missing in 2A)
    unfiled_by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    for i in ineligible.get("not_filed", []):
        unfiled_by_gstin[i.gstin].append(i)

    # Unclaimed (on Portal, missing in Books)
    unclaimed_by_gstin: dict[str, list[Invoice]] = defaultdict(list)
    for i in unclaimed.get("missing_invoice", []):
        unclaimed_by_gstin[i.gstin].append(i)

    all_gstins = set(booked_by_gstin.keys()) | set(portal_by_gstin.keys())
    scorecards: list[VendorScorecard] = []

    for g in sorted(all_gstins):
        name = names_by_gstin.get(g, "Unknown Supplier")
        p_num = pan(g)
        is_conflict = p_num in conflict_pans

        b_invoices = booked_by_gstin.get(g, [])
        p_invoices = portal_by_gstin.get(g, [])
        m_pairs = matched_by_gstin.get(g, [])
        u_invoices = unfiled_by_gstin.get(g, [])
        unc_invoices = unclaimed_by_gstin.get(g, [])

        b_tax = round(sum(i.tax for i in b_invoices), 2)
        p_tax = round(sum(i.tax for i in p_invoices), 2)
        m_tax = round(sum(p.gstr.tax for p in m_pairs), 2)
        u_tax = round(sum(i.tax for i in u_invoices), 2)
        unc_tax = round(sum(i.tax for i in unc_invoices), 2)

        # Compliance rate based on inward booked vs verified on portal
        if b_tax > 0:
            comp_rate = round(min(100.0, (m_tax / b_tax) * 100.0), 1)
        elif p_tax > 0:
            comp_rate = 100.0
        else:
            comp_rate = 0.0

        # Determine Grade & IMS Action
        if is_conflict:
            grade = "D"
            ims_action = "LEDGER FIX"
            recom = "Multi-State PAN registration conflict. Re-align vendor ledger in Tally before taking action."
        elif u_tax >= 25000.0 or comp_rate < 75.0:
            grade = "C"
            ims_action = "REJECT"
            recom = f"High Risk: Rs {u_tax:,.0f} unfiled tax. Issue Section 16(2)(c) dispute letter; hold vendor payments."
        elif u_tax > 0 or unc_tax > 0:
            grade = "B"
            ims_action = "HOLD PENDING"
            recom = "Moderate Risk: Timing lag detected. Keep invoices in IMS Pending state pending next month's return."
        else:
            grade = "A"
            ims_action = "ACCEPT"
            recom = "Compliant: 100% verified against portal. Safe to ACCEPT in IMS and claim full ITC in GSTR-3B."

        scorecards.append(VendorScorecard(
            gstin=g,
            name=name,
            pan=p_num,
            booked_count=len(b_invoices),
            booked_tax=b_tax,
            portal_count=len(p_invoices),
            portal_tax=p_tax,
            matched_count=len(m_pairs),
            matched_tax=m_tax,
            unfiled_count=len(u_invoices),
            unfiled_tax=u_tax,
            unclaimed_count=len(unc_invoices),
            unclaimed_tax=unc_tax,
            multi_state_conflict=is_conflict,
            compliance_rate=comp_rate,
            grade=grade,
            ims_action=ims_action,
            ims_recommendation=recom,
        ))

    # Sort scorecards: High risk (C, D) and largest unfiled tax first
    scorecards.sort(key=lambda s: (0 if s.grade in ("C", "D") else 1, -s.unfiled_tax, -s.booked_tax))

    # Aggregate counts
    g_a = sum(1 for s in scorecards if s.grade == "A")
    g_b = sum(1 for s in scorecards if s.grade == "B")
    g_c = sum(1 for s in scorecards if s.grade == "C")
    g_d = sum(1 for s in scorecards if s.grade == "D")

    ims_accept_tax = sum(s.matched_tax for s in scorecards if s.grade == "A")
    ims_accept_cnt = sum(s.matched_count for s in scorecards if s.grade == "A")

    ims_pending_tax = sum(s.unclaimed_tax for s in scorecards if s.grade == "B")
    ims_pending_cnt = sum(s.unclaimed_count for s in scorecards if s.grade == "B")

    ims_reject_tax = sum(s.unfiled_tax for s in scorecards if s.grade in ("C", "D"))
    ims_reject_cnt = sum(s.unfiled_count for s in scorecards if s.grade in ("C", "D"))

    top_risk = [s for s in scorecards if s.grade in ("C", "D") and (s.unfiled_tax > 0 or s.multi_state_conflict)][:10]

    summary = IMSAggregateSummary(
        total_vendors_analyzed=len(scorecards),
        grade_a_count=g_a,
        grade_b_count=g_b,
        grade_c_count=g_c,
        grade_d_count=g_d,
        ims_accept_tax=round(ims_accept_tax, 2),
        ims_accept_count=ims_accept_cnt,
        ims_pending_tax=round(ims_pending_tax, 2),
        ims_pending_count=ims_pending_cnt,
        ims_reject_tax=round(ims_reject_tax, 2),
        ims_reject_count=ims_reject_cnt,
        top_risk_vendors=top_risk,
    )

    return scorecards, summary
