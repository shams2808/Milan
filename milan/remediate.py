"""Turn the exception list into drafted actions a practitioner can send.

THE DIVISION OF LABOUR, AND WHY
-------------------------------
The practitioner's own words, when asked whether an LLM should help decide
what is blocked or what matches:

    "our experience tells us more than your AI model"

He is right, and it settles the architecture. The model is not here to know
GST law or to judge a match -- he knows both better than it does. It is here
so he does not type the same letter fourteen times.

So:
    deterministic  ->  WHICH suppliers, WHICH invoices, WHICH figures,
                       WHAT the discrepancy is                (this file)
    LLM            ->  the prose wrapped around those facts   (draft.py)

FACTS ARE COMPUTED, NEVER GENERATED. Every number that appears in a draft
must already exist in Action.facts, and `verify_draft` rejects the draft if a
figure appears that was not computed. A letter to a supplier or a reply to a
GST officer carries figures that must survive scrutiny; a model that rounds
Rs 28,713 to "approximately Rs 29,000" has created a liability.

Nothing here sends anything. Every draft is for the advocate to read, edit and
send himself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .core import Invoice, indian_number_format, pan, rupees
from .match import Result
from .report import ITC_DEADLINE, classify_ineligible, classify_unclaimed, pan_conflicts

CHASE_SUPPLIER = "chase_supplier"
LEDGER_FIX = "ledger_fix"
NOTICE_REPLY = "notice_reply"


@dataclass
class Action:
    """One thing that needs doing, with the facts already established."""

    kind: str
    title: str
    recipient: str
    facts: dict                      # computed; the model may not add to this
    invoices: list[Invoice] = field(default_factory=list)
    draft: str = ""                  # filled by draft.py, or left empty

    @property
    def value(self) -> float:
        return round(sum(i.tax for i in self.invoices), 2)


def _fact_numbers(facts: dict) -> set[str]:
    """Every number a draft is allowed to contain, in the forms it might be
    written: 28713, 28713.00, 28,713, 28,713.00, 1,45,200, 1,45,200.00."""
    allowed: set[str] = set()

    def add(value):
        if isinstance(value, (int, float)):
            for text in (f"{value:.2f}", f"{value:,.2f}", f"{value:,.0f}", f"{value:.0f}",
                         indian_number_format(value, 2), indian_number_format(value, 0)):
                allowed.add(text)
                allowed.add(text.replace(",", ""))
        elif isinstance(value, str):
            for token in re.findall(r"\d[\d,]*\.?\d*", value):
                allowed.add(token)
                allowed.add(token.replace(",", ""))
        elif isinstance(value, date):
            allowed.update({str(value.day), str(value.year), value.isoformat()})
        elif isinstance(value, (list, tuple)):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            for item in value.values():
                add(item)

    add(facts)
    return allowed


def verify_draft(action: Action, draft: str) -> list[str]:
    """Return every figure in `draft` that was not computed. Empty means clean.

    This is the guardrail that lets an LLM near a document a GST officer will
    read. The model writes sentences; it does not get to invent, restate
    loosely, or round a figure. Anything it produces that we did not compute
    is reported here and the draft is rejected.
    """
    allowed = _fact_numbers(action.facts)
    invented = []
    for token in re.findall(r"\d[\d,]*\.?\d*", draft):
        bare = token.replace(",", "").rstrip(".")
        if token in allowed or bare in allowed:
            continue
        # Ordinary prose integers
        if bare.isdigit() and len(bare) <= 4 and float(bare) <= 2100:
            if bare in allowed:
                continue
            invented.append(token)
            continue
        invented.append(token)
    return invented


def plan(res: Result, tally: list[Invoice], gstr: list[Invoice]) -> list[Action]:
    """Everything that needs doing, largest money first.

    Read this as the agent's plan: it inspects the reconciliation state and
    decides which actions the situation calls for. No model is involved in
    deciding -- the decision follows from which bucket an invoice landed in.
    """
    ineligible = classify_ineligible(res, gstr)
    actions: list[Action] = []
    days_left = (ITC_DEADLINE - date.today()).days

    # 1. Suppliers who have not filed: chase them, or the ITC must be reversed.
    by_supplier: dict[tuple[str, str], list[Invoice]] = {}
    for inv in ineligible.get("not_filed", []):
        by_supplier.setdefault((inv.gstin, inv.supplier), []).append(inv)

    for (gstin, name), invoices in by_supplier.items():
        invoices.sort(key=lambda i: -i.tax)
        actions.append(Action(
            kind=CHASE_SUPPLIER,
            title=f"Ask {name} to file {len(invoices)} invoice(s)",
            recipient=name,
            invoices=invoices,
            facts={
                "supplier_name": name,
                "supplier_gstin": gstin,
                "invoice_count": len(invoices),
                "total_tax": round(sum(i.tax for i in invoices), 2),
                "total_taxable": round(sum(i.taxable for i in invoices), 2),
                "statutory_sections": ["16", "2", "50", "3", "18", "2017", "2024", "2025", "2026"],
                "invoices": [
                    {"number": i.inv_no, "date": i.inv_date.isoformat(),
                     "taxable": i.taxable, "tax": i.tax}
                    for i in invoices
                ],
                "consequence": "ITC claimed on these invoices is not available "
                               "until the supplier files, and attracts interest "
                               "under section 50 if it remains claimed.",
            },
        ))

    # 2. Same supplier PAN under two registrations: a books correction.
    for pn, books_gstins, portal_gstins, b_count, b_tax, p_count, p_tax in pan_conflicts(res, tally, gstr):
        if not books_gstins or not portal_gstins:
            continue
        actions.append(Action(
            kind=LEDGER_FIX,
            title=f"Correct GSTIN in Tally for PAN {pn}",
            recipient="books",
            facts={
                "pan": pn,
                "booked_under": books_gstins,
                "portal_shows": portal_gstins,
                "invoice_count": p_count,
                "total_tax": p_tax,
                "consequence": "The same invoices sit in both piles until the "
                               "ledger points at the registration the supplier "
                               "actually billed from.",
            },
        ))

    actions.sort(key=lambda a: -a.facts.get("total_tax", 0.0))
    return actions


def notice_reply_action(res: Result, tally: list[Invoice], gstr: list[Invoice], *,
                        notice_ref: str = "", notice_type: str = "ASMT-10",
                        period: str = "FY 2025-26") -> Action:
    """The reconciliation, arranged as the answer to a departmental notice.

    A scrutiny notice on ITC asks one question: why does the credit claimed
    differ from what GSTR-2A supports. Every figure needed to answer it has
    already been computed, so the reply is a presentation problem, not an
    analysis problem.
    """
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)

    matched_tax = round(sum(p.gstr.tax for p in res.pairs), 2)
    not_filed = ineligible.get("not_filed", [])
    other_reg = unclaimed.get("other_registration", [])
    missing = unclaimed.get("missing_invoice", [])
    absent = unclaimed.get("supplier_absent", [])

    return Action(
        kind=NOTICE_REPLY,
        title=f"Draft reply to {notice_type} for {period}",
        recipient="The Proper Officer",
        facts={
            "notice_type": notice_type,
            "notice_ref": notice_ref,
            "period": period,
            "gstr2a_invoice_count": len(gstr),
            "books_invoice_count": len(tally),
            "matched_invoice_count": len(res.pairs),
            "matched_tax": matched_tax,
            "not_filed_count": len(not_filed),
            "not_filed_tax": round(sum(i.tax for i in not_filed), 2),
            "wrong_registration_count": len(other_reg),
            "wrong_registration_tax": round(sum(i.tax for i in other_reg), 2),
            "unclaimed_count": len(missing),
            "unclaimed_tax": round(sum(i.tax for i in missing), 2),
            "other_ledger_count": len(absent),
            "other_ledger_tax": round(sum(i.tax for i in absent), 2),
        },
    )


def generate_legal_chase_notice(action: Action, company_name: str = "Our Finance Department") -> str:
    """Generate a legally sound statutory demand notice quoting Section 16(2)(c)."""
    f = action.facts
    inv_rows = []
    for inv in f.get("invoices", []):
        inv_rows.append(f"| {inv['number']} | {inv['date']} | Rs {indian_number_format(inv['taxable'], 2)} | Rs {indian_number_format(inv['tax'], 2)} |")

    table_str = "\n".join(inv_rows)

    return f"""DEMAND NOTICE: NON-FILING OF GSTR-1 & ITC COMPLIANCE UNDER SECTION 16(2)(c)

To: {f['supplier_name']}
GSTIN: {f['supplier_gstin']}

Dear Accounts / Taxation Team,

Sub: Urgent filing of {f['invoice_count']} invoice(s) totalling Rs {indian_number_format(f['total_tax'], 2)} in GSTR-1

We are reviewing our Input Tax Credit (ITC) reconciliation for the financial year. Upon verification of the GST Portal (GSTR-2A/2B), we note that the following supply invoices issued by your organization have NOT been reflected in our inward portal records:

| Invoice Number | Invoice Date | Taxable Value | Total Tax |
| :--- | :--- | :--- | :--- |
{table_str}

Summary of Unfiled Invoices:
- Total Invoices: {f['invoice_count']}
- Total Taxable Value: Rs {indian_number_format(f['total_taxable'], 2)}
- Total GST (ITC at Stake): Rs {indian_number_format(f['total_tax'], 2)}

STATUTORY REQUIREMENT:
Under Section 16(2)(c) of the Central Goods and Services Tax (CGST) Act, 2017, input tax credit is legally contingent upon the actual payment and reporting of tax by the supplier. Furthermore, Section 50(3) imposes an 18% per annum interest liability on unverified credit.

REQUESTED ACTION:
Please ensure that all the above invoices are uploaded in your immediate upcoming GSTR-1 return. Kindly furnish the filing ARN / IFF acknowledgment within seven business days to avoid withholding of future payment disbursements.

Yours faithfully,
{company_name}"""


def generate_ledger_fix_directive(action: Action) -> str:
    """Generate internal accounting directive for multi-state PAN ledger realignment."""
    f = action.facts
    return f"""INTERNAL ACCOUNTING DIRECTIVE: MULTI-STATE GSTIN LEDGER REALIGNMENT

Target Supplier PAN: {f['pan']}
Current Tally Ledger GSTIN: {' / '.join(f['booked_under'])}
Actual Portal Billing GSTIN: {' / '.join(f['portal_shows'])}
Invoices Affected: {f['invoice_count']}
Total Tax Involved: Rs {indian_number_format(f['total_tax'], 2)}

BACKGROUND:
The supplier operates registrations in multiple states under the same PAN. The supplier issued invoices from {', '.join(f['portal_shows'])}, but our accounting vouchers were entered under {', '.join(f['booked_under'])}.

REQUIRED ACTIONS IN TALLY ERP:
1. Create a distinct ledger account for each state registration (e.g., '{f['pan']} - {f['portal_shows'][0][:2]} State').
2. Update the supplier GSTIN on affected purchase vouchers from {f['booked_under'][0]} to {f['portal_shows'][0]}.
3. Re-run Milan reconciliation to confirm clean auto-matching.
"""


def print_plan(actions: list[Action]) -> None:
    total = sum(a.facts.get("total_tax", 0.0) for a in actions)
    print(f"\n{'=' * 78}")
    print(f"ACTION PLAN  {len(actions)} items, {rupees(total)} at stake")
    print(f"{'=' * 78}")
    for i, a in enumerate(actions, 1):
        print(f"\n  {i}. [{a.kind}] {a.title}")
        if a.kind == CHASE_SUPPLIER:
            print(f"     {a.facts['supplier_gstin']}  {rupees(a.facts['total_tax'])}"
                  f"  across {a.facts['invoice_count']} invoice(s)")
            for inv in a.facts["invoices"][:3]:
                print(f"       {inv['number']:<22} {inv['date']}  {rupees(inv['tax'])}")
            if len(a.facts["invoices"]) > 3:
                print(f"       ... {len(a.facts['invoices']) - 3} more")
        elif a.kind == LEDGER_FIX:
            print(f"     books {'/'.join(a.facts['booked_under'])}"
                  f"  ->  2A {'/'.join(a.facts['portal_shows'])}"
                  f"   {rupees(a.facts['total_tax'])}")
        print(f"     draft: {'ready' if a.draft else 'not generated'}")

