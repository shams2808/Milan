"""Rule 88D (DRC-01C) Notice Shield, Forward Cash Forecaster, and Section 50 Interest Engine.

Built for enterprise FinOps controllers managing working capital and GST scrutiny risks.
Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from .core import GSTR3BSummary, Invoice, ThreeWayPosition, indian_number_format, rupees
from .match import Result
from .report import ITC_DEADLINE, classify_ineligible


@dataclass
class Rule88DRisk:
    risk_level: str  # "SAFE", "ELEVATED", "CRITICAL"
    excess_claimed_tax: float
    excess_percentage: float
    is_drc01c_imminent: bool
    summary: str
    remedy: str


@dataclass
class CashForecast:
    avg_monthly_tax_liability: float
    avg_monthly_verified_itc: float
    closing_itc_balance: float
    forecast_net_cash_outflow_next_month: float
    trapped_working_capital_unfiled: float
    total_unfiled_invoices_count: int


@dataclass
class Section50Interest:
    total_ineligible_tax_claimed: float
    annual_interest_rate: float  # 18.0%
    estimated_interest_exposure: float
    invoice_count: int
    days_accruing_avg: int


@dataclass
class FinOpsForecastReport:
    rule_88d: Rule88DRisk
    cash_forecast: CashForecast
    sec_50_interest: Section50Interest


def evaluate_rule_88d_risk(
    pos: ThreeWayPosition,
    tolerance_pct: float = 20.0,
    monetary_threshold: float = 2500000.0,
) -> Rule88DRisk:
    """Evaluate Form DRC-01C / Rule 88D scrutiny risk.

    Under Rule 88D, when GSTR-3B Table 4A ITC availed exceeds GSTR-2B/2A available credit
    by a defined percentage (typically 20%) and monetary limit (typically Rs 25 Lakhs),
    the GST portal automatically issues Form DRC-01C Part A requiring response or payment within 7 days.
    """
    claimed = pos.claimed_3b
    available = pos.available_2a

    if claimed <= available:
        return Rule88DRisk(
            risk_level="SAFE",
            excess_claimed_tax=0.0,
            excess_percentage=0.0,
            is_drc01c_imminent=False,
            summary=f"GSTR-3B claims ({rupees(claimed)}) are within available GSTR-2A credit ({rupees(available)}).",
            remedy="No DRC-01C risk. Maintain monthly Table 8 reconciliation working papers for statutory audit.",
        )

    excess = round(claimed - available, 2)
    excess_pct = round((excess / available) * 100.0, 2) if available > 0 else 100.0

    if excess_pct >= tolerance_pct and excess >= monetary_threshold:
        return Rule88DRisk(
            risk_level="CRITICAL",
            excess_claimed_tax=excess,
            excess_percentage=excess_pct,
            is_drc01c_imminent=True,
            summary=(
                f"HIGH RISK OF FORM DRC-01C (RULE 88D): GSTR-3B claims exceed portal credit by "
                f"{excess_pct:.1f}% ({rupees(excess)} excess)."
            ),
            remedy=(
                "Mandatory DRC-01C response needed if notice arrives. Prepare reconciliation annexure "
                "separating imports, ISD, RCM credits, and verified timing differences."
            ),
        )
    elif excess_pct >= 10.0 or excess >= 500000.0:
        return Rule88DRisk(
            risk_level="ELEVATED",
            excess_claimed_tax=excess,
            excess_percentage=excess_pct,
            is_drc01c_imminent=False,
            summary=(
                f"ELEVATED RISK: GSTR-3B claim exceeds 2A by {excess_pct:.1f}% ({rupees(excess)})."
            ),
            remedy=(
                "Review non-2A ITC inclusions (Imports, ISD, RCM) to ensure proper categorization before next return."
            ),
        )
    else:
        return Rule88DRisk(
            risk_level="SAFE",
            excess_claimed_tax=excess,
            excess_percentage=excess_pct,
            is_drc01c_imminent=False,
            summary=(
                f"Nominal variance of {excess_pct:.1f}% ({rupees(excess)}), within safe compliance limits."
            ),
            remedy="Standard month-end ledger reconciliation suffices.",
        )


def calculate_section_50_interest(
    res: Result,
    gstr: Sequence[Invoice],
    interest_rate: float = 0.18,
) -> Section50Interest:
    """Calculate potential Section 50(3) interest penalty (18% p.a.) on unfiled ITC.

    Invoices booked in Tally where suppliers never uploaded GSTR-1 are ineligible for ITC
    under Section 16(2)(c). If availed and utilized, interest runs at 18% p.a.
    """
    ineligible = classify_ineligible(res, gstr)
    unfiled = ineligible.get("not_filed", [])
    if not unfiled:
        return Section50Interest(
            total_ineligible_tax_claimed=0.0,
            annual_interest_rate=interest_rate * 100.0,
            estimated_interest_exposure=0.0,
            invoice_count=0,
            days_accruing_avg=0,
        )

    today = date.today()
    total_tax = sum(i.tax for i in unfiled)
    total_interest = 0.0
    total_days = 0

    for inv in unfiled:
        days = max(1, (today - inv.inv_date).days)
        total_days += days
        # Simple interest: Principal * Rate * (Days / 365)
        total_interest += inv.tax * interest_rate * (days / 365.0)

    avg_days = total_days // len(unfiled) if unfiled else 0

    return Section50Interest(
        total_ineligible_tax_claimed=round(total_tax, 2),
        annual_interest_rate=interest_rate * 100.0,
        estimated_interest_exposure=round(total_interest, 2),
        invoice_count=len(unfiled),
        days_accruing_avg=avg_days,
    )


def forecast_cash_position(
    tally: Sequence[Invoice],
    gstr: Sequence[Invoice],
    res: Result,
    gstr3b: GSTR3BSummary | None,
) -> CashForecast:
    """Forecast next month's net GST cash outflow and trapped vendor capital."""
    ineligible = classify_ineligible(res, gstr)
    unfiled = ineligible.get("not_filed", [])
    trapped_capital = sum(i.tax for i in unfiled)

    if gstr3b and len(gstr3b.months) > 0:
        # Based on filed 3B return history
        avg_liability = gstr3b.total_tax_liability / len(gstr3b.months)
        avg_verified_itc = sum(p.gstr.tax for p in res.pairs) / max(1, len(gstr3b.months))
        closing_bal = gstr3b.closing_balance
    else:
        # Based on Tally booked activity
        total_tally_tax = sum(i.tax for i in tally)
        avg_liability = (total_tally_tax * 1.15) / 12.0  # Approx 15% value-add output
        avg_verified_itc = sum(p.gstr.tax for p in res.pairs) / 12.0
        closing_bal = 0.0

    # Net Cash Outflow Forecast = Max(0, Output Liability - Verified ITC - Available Balance)
    net_cash_outflow = max(0.0, avg_liability - avg_verified_itc - closing_bal)

    return CashForecast(
        avg_monthly_tax_liability=round(avg_liability, 2),
        avg_monthly_verified_itc=round(avg_verified_itc, 2),
        closing_itc_balance=round(closing_bal, 2),
        forecast_net_cash_outflow_next_month=round(net_cash_outflow, 2),
        trapped_working_capital_unfiled=round(trapped_capital, 2),
        total_unfiled_invoices_count=len(unfiled),
    )


def compute_finops_forecast(
    tally: Sequence[Invoice],
    gstr: Sequence[Invoice],
    res: Result,
    pos: ThreeWayPosition | None,
    gstr3b: GSTR3BSummary | None,
) -> FinOpsForecastReport:
    """Aggregate complete FinOps forecasting and statutory scrutiny shield."""
    if pos is not None:
        rule_88d = evaluate_rule_88d_risk(pos)
    else:
        # Approximate 2-way position
        avail_2a = sum(i.tax for i in gstr)
        booked = sum(i.tax for i in tally)
        matched = sum(p.gstr.tax for p in res.pairs)
        approx_pos = ThreeWayPosition(
            available_2a=avail_2a,
            booked_tally=booked,
            matched_tax=matched,
            claimed_3b=booked,
            matched_unclaimed=0.0,
            gap_2a_3b=0.0,
            only_tally_tax=sum(i.tax for i in res.only_tally),
            only_2a_tax=sum(i.tax for i in res.only_gstr),
        )
        rule_88d = evaluate_rule_88d_risk(approx_pos)

    sec_50 = calculate_section_50_interest(res, gstr)
    cash_fc = forecast_cash_position(tally, gstr, res, gstr3b)

    return FinOpsForecastReport(
        rule_88d=rule_88d,
        cash_forecast=cash_fc,
        sec_50_interest=sec_50,
    )
