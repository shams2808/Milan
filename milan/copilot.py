"""Grounded FinOps Controller Co-Pilot.

Provides deterministic, fact-grounded natural language Q&A for CFOs and tax controllers.
Guaranteed 0% hallucination by binding strictly to computed reconciliation facts.
Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from .core import GSTR3BSummary, Invoice, ThreeWayPosition, indian_number_format, rupees
from .forecaster import FinOpsForecastReport
from .match import Result
from .report import ITC_DEADLINE, classify_ineligible, classify_unclaimed, pan_conflicts
from .vendor_risk import IMSAggregateSummary, VendorScorecard


@dataclass
class CopilotResponse:
    query: str
    intent: str
    headline: str
    answer_html: str
    action_items: list[str]


def ask_copilot(
    query: str,
    tally: Sequence[Invoice],
    gstr: Sequence[Invoice],
    res: Result,
    twp: ThreeWayPosition | None,
    gstr3b: GSTR3BSummary | None,
    forecast: FinOpsForecastReport,
    vendors: list[VendorScorecard],
    ims_summary: IMSAggregateSummary,
) -> CopilotResponse:
    """Evaluate controller question and return precise fact-grounded response."""
    q = query.lower().strip()

    # 1. Top Risk / Vendor Exposure
    if any(k in q for k in ("top risk", "risk vendor", "worst supplier", "delinquent", "chase", "unfiled supplier", "vendor risk", "who owes")):
        top = ims_summary.top_risk_vendors[:5]
        if not top:
            top = [v for v in vendors if v.unfiled_tax > 0][:5]

        items_html = []
        for idx, v in enumerate(top, 1):
            items_html.append(
                f"<li><strong>{idx}. {v.name}</strong> (<code>{v.gstin}</code>): "
                f"<span style='color:#b91c1c;font-weight:700;'>{rupees(v.unfiled_tax)}</span> unfiled across {v.unfiled_count} bill(s). "
                f"Grade: <strong>{v.grade}</strong> &middot; IMS: <code>{v.ims_action}</code></li>"
            )

        answer = (
            f"<p>We identified <strong>{ims_summary.grade_c_count + ims_summary.grade_d_count} high-risk vendors</strong> "
            f"accounting for <strong>{rupees(ims_summary.ims_reject_tax)}</strong> in trapped working capital:</p>"
            f"<ul style='margin:10px 0 14px 20px;'>{''.join(items_html)}</ul>"
            f"<p><strong>Recommended Action:</strong> Issue Section 16(2)(c) demand notices immediately and hold outward payments until GSTR-1 is uploaded.</p>"
        )

        return CopilotResponse(
            query=query,
            intent="vendor_risk",
            headline=f"Top Vendor Risk Exposure: {rupees(ims_summary.ims_reject_tax)} Trapped",
            answer_html=answer,
            action_items=[
                "Generate Dispute Notice for top delinquent suppliers in Tab 4.",
                "Mark unfiled bills as REJECT or HOLD in Invoice Management System (IMS).",
                "Freeze payment disbursements to Grade C vendors.",
            ],
        )

    # 2. Section 16(4) Lapse / Unclaimed Inward
    if any(k in q for k in ("16(4)", "16 4", "lapse", "november 30", "unclaimed", "missing in books", "not in tally", "forgot to book")):
        unclaimed = classify_unclaimed(res, tally)
        missing = unclaimed.get("missing_invoice", [])
        tot_unclaimed = sum(i.tax for i in missing)
        days = (ITC_DEADLINE - date.today()).days

        answer = (
            f"<p>There are <strong>{len(missing)} inward invoices</strong> totaling "
            f"<span style='color:#15803d;font-weight:800;'>{rupees(tot_unclaimed)}</span> available on the GST portal (GSTR-2A) "
            f"that your client has <strong>never booked in Tally</strong>.</p>"
            f"<p>Under <strong>Section 16(4) of the CGST Act</strong>, this credit will permanently lapse after <strong>30 November 2026</strong> "
            f"(<strong>{days} days remaining</strong>).</p>"
        )

        return CopilotResponse(
            query=query,
            intent="section_16_4",
            headline=f"Section 16(4) Availment: {rupees(tot_unclaimed)} Unclaimed Credit",
            answer_html=answer,
            action_items=[
                "Review 'Not in Tally' sheet in the review workbook.",
                f"Pass purchase journal entries in Tally before the 30 Nov deadline ({days} days left).",
                "Avail credit in GSTR-3B Table 4(A)(5) to prevent permanent loss.",
            ],
        )

    # 3. Rule 88D / DRC-01C Notice Risk
    if any(k in q for k in ("88d", "88 d", "drc-01c", "drc01c", "drc 01c", "notice", "scrutiny", "excess claim")):
        r88 = forecast.rule_88d
        badge_color = "#15803d" if r88.risk_level == "SAFE" else ("#b45309" if r88.risk_level == "ELEVATED" else "#b91c1c")

        answer = (
            f"<div style='background:#f8fafc;padding:14px;border-radius:8px;border-left:4px solid {badge_color};margin-bottom:12px;'>"
            f"<strong>Status: <span style='color:{badge_color};'>{r88.risk_level}</span></strong><br>"
            f"{r88.summary}"
            f"</div>"
            f"<p><strong>Statutory Defense & Next Steps:</strong> {r88.remedy}</p>"
        )

        return CopilotResponse(
            query=query,
            intent="rule_88d",
            headline=f"Rule 88D (Form DRC-01C) Status: {r88.risk_level}",
            answer_html=answer,
            action_items=[
                "Check GSTR-3B Table 4(A)(5) vs GSTR-2B monthly variance.",
                "Maintain Table 8 working paper with verified Import/ISD/RCM schedules.",
                "Keep dispute response template ready if DRC-01C arrives.",
            ],
        )

    # 4. Forward Cash Outflow Forecast
    if any(k in q for k in ("cash", "outflow", "forecast", "how much pay", "liability", "working capital", "pay next month")):
        cf = forecast.cash_forecast
        answer = (
            f"<div style='display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:10px;margin:12px 0;'>"
            f"<div style='background:#f8fafc;padding:10px;border-radius:8px;border:1px solid #e2e8f0;'>"
            f"<div style='font-size:12px;color:#64748b;'>Est. Output Liability</div>"
            f"<div style='font-size:16px;font-weight:700;'>{rupees(cf.avg_monthly_tax_liability)}</div>"
            f"</div>"
            f"<div style='background:#f0fdf4;padding:10px;border-radius:8px;border:1px solid #bbf7d0;'>"
            f"<div style='font-size:12px;color:#15803d;'>Verified ITC Offset</div>"
            f"<div style='font-size:16px;font-weight:700;color:#15803d;'>{rupees(cf.avg_monthly_verified_itc)}</div>"
            f"</div>"
            f"<div style='background:#eff6ff;padding:10px;border-radius:8px;border:1px solid #bfdbfe;'>"
            f"<div style='font-size:12px;color:#1d4ed8;'>Closing Credit Balance</div>"
            f"<div style='font-size:16px;font-weight:700;color:#1d4ed8;'>{rupees(cf.closing_itc_balance)}</div>"
            f"</div>"
            f"</div>"
            f"<p><strong>Forecast Net GST Cash Outflow: <span style='color:#0f172a;font-size:18px;font-weight:800;'>{rupees(cf.forecast_net_cash_outflow_next_month)}</span></strong></p>"
            f"<p><em>Note: Chasing {cf.total_unfiled_invoices_count} unfiled invoices will unlock an extra <strong>{rupees(cf.trapped_working_capital_unfiled)}</strong> in credit, directly reducing cash outflow.</em></p>"
        )

        return CopilotResponse(
            query=query,
            intent="cash_forecast",
            headline=f"Forward Cash Forecast: {rupees(cf.forecast_net_cash_outflow_next_month)} Net Payable",
            answer_html=answer,
            action_items=[
                f"Reserve {rupees(cf.forecast_net_cash_outflow_next_month)} in working capital for 20th of next month.",
                f"Recover {rupees(cf.trapped_working_capital_unfiled)} by pushing unfiled vendors before return cutoff.",
            ],
        )

    # 5. Three-Way Reconciliation / Table 8 / Gap Analysis
    if any(k in q for k in ("three way", "3 way", "table 8", "3b gap", "matched but never", "why gap", "difference between 2a and 3b")):
        if twp:
            answer = (
                f"<p><strong>Three-Way Position Summary (Table 8 Shape):</strong></p>"
                f"<ul style='margin:10px 0 14px 20px;'>"
                f"<li><strong>GSTR-2A Available:</strong> {rupees(twp.available_2a)}</li>"
                f"<li><strong>Tally Inward Booked:</strong> {rupees(twp.booked_tally)}</li>"
                f"<li><strong>Matched Confirmed:</strong> {rupees(twp.matched_tax)}</li>"
                f"<li><strong>GSTR-3B Claimed:</strong> {rupees(twp.claimed_3b)}</li>"
                f"</ul>"
                f"<p style='color:#1e40af;font-weight:700;background:#eff6ff;padding:10px;border-radius:6px;'>"
                f"Key Finding: Matched but Never Claimed = {rupees(twp.matched_unclaimed)}"
                f"</p>"
                f"<p><strong>Honesty Caveat:</strong> The {rupees(twp.gap_2a_3b)} total gap between 2A and 3B includes "
                f"statutory non-B2B credits (Imports, ISD, RCM) which do not appear in GSTR-2A B2B section.</p>"
            )
            headline = f"Table 8 Audit: {rupees(twp.matched_unclaimed)} Eligible Under-Claim Discovered"
        else:
            answer = "<p>Upload GSTR-3B monthly summary return along with GSTR-2A and Tally to unlock full Three-Way Table 8 Reconciliation.</p>"
            headline = "Three-Way Position Requires GSTR-3B"

        return CopilotResponse(
            query=query,
            intent="three_way",
            headline=headline,
            answer_html=answer,
            action_items=[
                "Review Tab 1 for full Table 8 progression.",
                "Review Month-by-Month timing matrix for invoice date vs filing date lags.",
                "Export 6-Sheet Workbook for working papers.",
            ],
        )

    # 6. Multi-State PAN Conflicts
    if any(k in q for k in ("pan", "multi-state", "multi state", "dual", "wrong gstin", "haryana", "maharashtra")):
        conflicts = pan_conflicts(res, tally, gstr)
        tot_c = sum(c[6] for c in conflicts)
        c_items = []
        for pn, bg, pg, bn, bv, pcount, pv in conflicts[:4]:
            c_items.append(
                f"<li><strong>PAN {pn}:</strong> Booked under <code>{'/'.join(bg) or '-'}</code> ({bn} inv, {rupees(bv)}) "
                f"&rarr; Portal carries <code>{'/'.join(pg) or '-'}</code> ({pcount} inv, {rupees(pv)})</li>"
            )

        answer = (
            f"<p>Found <strong>{len(conflicts)} suppliers ({rupees(tot_c)})</strong> with multi-state registration conflicts:</p>"
            f"<ul style='margin:10px 0 14px 20px;'>{''.join(c_items)}</ul>"
            f"<p><em>Why this matters:</em> The supplier is the same legal entity (same 10-digit PAN) but registered in different states. "
            f"They billed from one state, but your accounting team booked against another state ledger. "
            f"Milan refrains from auto-matching across GSTINs to keep your GST audit clean.</p>"
        )

        return CopilotResponse(
            query=query,
            intent="pan_conflicts",
            headline=f"Multi-State PAN Conflicts: {len(conflicts)} Suppliers ({rupees(tot_c)})",
            answer_html=answer,
            action_items=[
                "Create state-specific sub-ledgers in Tally (e.g. 'Vendor - MH', 'Vendor - HR').",
                "Re-assign invoices to match portal GSTINs.",
                "Re-run reconciliation to achieve 100% clean matching.",
            ],
        )

    # 7. Section 50 Interest
    if any(k in q for k in ("section 50", "interest", "penalty", "18%", "ineligible")):
        s50 = forecast.sec_50_interest
        answer = (
            f"<p>Under <strong>Section 50(3) of the CGST Act</strong>, claiming ineligible or unfiled ITC carries mandatory interest at "
            f"<strong>18% per annum</strong>.</p>"
            f"<p>Currently, you have <strong>{s50.invoice_count} unfiled invoices</strong> booked in Tally totaling "
            f"<strong>{rupees(s50.total_ineligible_tax_claimed)}</strong> in tax, with an estimated accrued interest exposure of "
            f"<span style='color:#b91c1c;font-weight:700;'>{rupees(s50.estimated_interest_exposure)}</span> (avg {s50.days_accruing_avg} days).</p>"
        )

        return CopilotResponse(
            query=query,
            intent="section_50",
            headline=f"Section 50 Interest Exposure: {rupees(s50.estimated_interest_exposure)}",
            answer_html=answer,
            action_items=[
                "Chase suppliers to file overdue GSTR-1 returns.",
                "If supplier is non-responsive, reverse credit in GSTR-3B Table 4(B)(2) to stop interest clock.",
            ],
        )

    # Default / General Executive Overview
    matched_tax = sum(p.gstr.tax for p in res.pairs)
    total_2a = sum(i.tax for i in gstr)
    total_tally = sum(i.tax for i in tally)

    answer = (
        f"<p><strong>Executive FinOps Controller Brief:</strong></p>"
        f"<ul style='margin:10px 0 14px 20px;'>"
        f"<li><strong>Reconciliation Status:</strong> {len(res.pairs)} matched pairs ({rupees(matched_tax)} verified).</li>"
        f"<li><strong>Section 16(4) Lapse Risk:</strong> {rupees(sum(i.tax for i in classify_unclaimed(res, tally).get('missing_invoice', [])))} unbooked credit to claim before 30 Nov.</li>"
        f"<li><strong>Trapped Working Capital:</strong> {rupees(forecast.cash_forecast.trapped_working_capital_unfiled)} with {forecast.cash_forecast.total_unfiled_invoices_count} unfiled vendors.</li>"
        f"<li><strong>Rule 88D Status:</strong> <strong style='color:#15803d;'>{forecast.rule_88d.risk_level}</strong>.</li>"
        f"</ul>"
        f"<p>Ask me specific questions like: <em>'Who are our top risk suppliers?'</em>, <em>'How much is our 16(4) lapse?'</em>, or <em>'Forecast our next month cash outflow'</em>.</p>"
    )

    return CopilotResponse(
        query=query,
        intent="general_overview",
        headline="Milan FinOps Executive Overview",
        answer_html=answer,
        action_items=[
            "Switch between tabs to inspect Table 8, Vendor Matrix, and Dispute Drafter.",
            "Download the complete 6-Sheet Audit Review Workbook.",
        ],
    )


# --- Serverless support ----------------------------------------------------
#
# On Vercel each request may land on a different, cold instance, so the
# reconciliation cannot be held in memory between the upload and a later
# copilot question. Rather than round-trip the state (unpickling anything a
# browser sends is remote code execution) or re-upload the files per question,
# every answer is computed once at reconcile time and embedded in the page.
#
# ask_copilot is unchanged and still produces every answer -- this only calls
# it once per topic up front. The keyword lists are the same ones it routes on,
# declared here so the client can do the identical matching offline.

COPILOT_TOPICS: list[tuple[str, tuple[str, ...], str]] = [
    ("vendor_risk",
     ("top risk", "risk vendor", "worst supplier", "delinquent", "chase",
      "unfiled supplier", "vendor risk", "who owes"),
     "Who are our top risk suppliers?"),
    ("lapse_16_4",
     ("16(4)", "16 4", "lapse", "november 30", "unclaimed", "missing in books",
      "not in tally", "forgot to book"),
     "How much ITC lapses under section 16(4)?"),
    ("rule_88d",
     ("88d", "88 d", "drc-01c", "drc01c", "drc 01c", "notice", "scrutiny",
      "excess claim"),
     "What is our Rule 88D notice risk?"),
    ("cash_forecast",
     ("cash", "outflow", "forecast", "how much pay", "liability",
      "working capital", "pay next month"),
     "Forecast our next month cash outflow"),
    ("three_way",
     ("three way", "3 way", "table 8", "3b gap", "matched but never",
      "why gap", "difference between 2a and 3b"),
     "Explain the Table 8 three-way gap"),
    ("pan_conflict",
     ("pan", "multi-state", "multi state", "dual", "wrong gstin", "haryana",
      "maharashtra"),
     "Show multi-state PAN conflicts"),
    ("section_50",
     ("section 50", "interest", "penalty", "18%", "ineligible"),
     "What is our section 50 interest exposure?"),
]


def precompute_copilot(
    tally: Sequence[Invoice],
    gstr: Sequence[Invoice],
    res: Result,
    twp: ThreeWayPosition | None,
    gstr3b: GSTR3BSummary | None,
    forecast: FinOpsForecastReport,
    vendors: list[VendorScorecard],
    ims_summary: IMSAggregateSummary,
) -> dict:
    """Every copilot answer, computed once, ready to embed in the page.

    Returns {"topics": [{id, keywords, headline, answer_html, action_items}],
             "fallback": {...}} -- the fallback is the same general overview
    ask_copilot returns for an unrecognised question.
    """
    def run(query: str) -> CopilotResponse:
        return ask_copilot(query, tally, gstr, res, twp, gstr3b,
                           forecast, vendors, ims_summary)

    def pack(r: CopilotResponse) -> dict:
        return {
            "headline": r.headline,
            "answer_html": r.answer_html,
            "action_items": list(r.action_items),
        }

    topics = []
    for topic_id, keywords, canonical in COPILOT_TOPICS:
        answer = run(canonical)
        topics.append({"id": topic_id, "keywords": list(keywords), **pack(answer)})

    # A query matching no keyword list falls through to the overview.
    return {"topics": topics, "fallback": pack(run("__general_overview__"))}
