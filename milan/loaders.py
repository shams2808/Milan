"""Loaders for real GSTR-2A and Tally exports.

Built directly against a real client's files (Heamons, FY 2025-26), not
against guessed schemas. Two things the guess would have gotten wrong:

  1. GSTR-2A's header is two merged rows -- a group row and a sub-header row
     -- and the useful text is split across both. `xlsx_lite.header_map`
     takes both and lets the more specific row win per column.

  2. Tally's Purchase Register has one column per LEDGER the client's chart
     of accounts actually uses ("Purchase 18%", "FEE FOR ISO CERTIFICATION",
     "Legal Expenses@18%", ...). Those names are specific to this one company
     and will not exist in anyone else's export. What Tally guarantees across
     every company is the standard report fields -- Value and Gross Total --
     so taxable = Value and tax = Gross Total - Value, and the ledger columns
     are never read at all.

Both loaders fail loudly (KeyError / ValueError) rather than returning an
empty or partial list, per the project's stated error-handling rule: a
reconciliation that silently ran on zero rows is worse than one that crashed.
"""

from __future__ import annotations

import re

from .core import Invoice
from .xlsx_lite import Workbook, excel_serial_to_date, header_map

_GSTR2A_KEYS = {
    "gstin of supplier": "gstin",
    "trade/legal name": "supplier",
    "invoice number": "inv_no",
    "invoice date": "inv_date",
    "taxable value": "taxable",
    "integrated tax": "igst",
    "central tax": "cgst",
    "state/ut tax": "sgst",
    "cess": "cess",
}

_TALLY_KEYS = {
    "date": "date",
    "particulars": "supplier",
    "voucher type": "voucher_type",
    "supplier invoice no": "inv_no",
    "gstin/uin": "gstin",
    "gross total": "gross_total",
}

# A real GST column: the header STARTS with the tax name, optionally followed
# by a rate -- "CGST @9%", "IGST@12%", "Cess".
#
# Anchoring at the start is what makes this safe. "Purchase IGST 18%" and
# "PURCHASE @IGST 5%" are purchase LEDGERS holding the taxable base, not tax;
# a substring search for "IGST" would sum the base into the tax and double the
# figure. Verified against the real file: gross == ledgers + tax + round-off on
# 1913 of 1915 rows, and the resulting tax matches GSTR-2A to the paisa.
_TAX_COL = re.compile(r"^(?:C|S|I|UT)GST\s*@?\s*[\d.]*\s*%?$|^CESS", re.I)


def _tax_kind(header: str) -> str:
    h = header.strip().upper()
    if h.startswith("CESS"):
        return "cess"
    if h.startswith("IGST"):
        return "igst"
    if h.startswith("CGST"):
        return "cgst"
    return "sgst"  # SGST / UTGST


def _f(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def _parse_ddmmyyyy(s: str):
    from datetime import datetime

    return datetime.strptime(s.strip(), "%d-%m-%Y").date()


def load_gstr2a(path: str) -> list[Invoice]:
    """The 'B2B - Only Invoice wise' sheet: one row per invoice, tax already
    aggregated across rate slabs. ('B2B - Invoice & Rate wise' has one row
    per rate slab per invoice and would need summing first -- deliberately
    not used, the portal already did that work for us.)
    """
    wb = Workbook(path)
    sheet = wb.find_sheet("Only Invoice")
    rows = list(wb.rows(sheet))

    header_rows = [r for r in rows if r.get("A") == "GSTIN of supplier" or r.get("C") == "Invoice number"]
    if len(header_rows) < 2:
        raise ValueError(f"expected a 2-row GSTR-2A header in {sheet!r}, found {len(header_rows)}")
    cols = header_map(header_rows, _GSTR2A_KEYS, merge_rows=len(header_rows))

    by_field = {v: k for k, v in cols.items()}
    out = []
    for i, r in enumerate(rows):
        gstin = r.get(by_field["gstin"])
        date_raw = r.get(by_field["inv_date"])
        # Title rows ("Goods and Services Tax - GSTR 2A", section headings)
        # land text in column A too, so a truthy GSTIN alone doesn't identify
        # a data row -- every real data row also has a date; no title row does.
        if not gstin or not date_raw or gstin == "GSTIN of supplier":
            continue
        out.append(
            Invoice(
                gstin=gstin.strip().upper(),
                supplier=(r.get(by_field["supplier"]) or "").strip(),
                inv_no=(r.get(by_field["inv_no"]) or "").strip(),
                inv_date=_parse_ddmmyyyy(date_raw),
                taxable=_f(r.get(by_field["taxable"])),
                igst=_f(r.get(by_field["igst"])),
                cgst=_f(r.get(by_field["cgst"])),
                sgst=_f(r.get(by_field["sgst"])),
                cess=_f(r.get(by_field["cess"])),
                source="2A",
                row_id=f"2A{i:06d}",
            )
        )
    if not out:
        raise ValueError(f"parsed 0 invoices from {path} -- header matched but no data rows found")
    return out


def load_tally_purchase(path: str) -> list[Invoice]:
    """The Purchase Register export. Filters to rows whose Voucher Type
    contains 'purchase' -- this file's sheet is pre-filtered already, but a
    Day Book export from a different client would not be, so the filter stays
    rather than assuming every export arrives pre-filtered.
    """
    wb = Workbook(path)
    sheet = next(
        (n for n in wb.sheet_names() if "purchase" in n.lower() or "day book" in n.lower()),
        wb.sheet_names()[0],
    )
    rows = list(wb.rows(sheet))

    header_row = next((r for r in rows if "particulars" in "".join(v or "" for v in r.values()).lower()
                        and "gstin" in "".join(v or "" for v in r.values()).lower()), None)
    if header_row is None:
        raise ValueError(f"could not find the header row in {sheet!r}")
    cols = header_map([header_row], _TALLY_KEYS, merge_rows=1)
    by_field = {v: k for k, v in cols.items()}

    # Which columns are actual GST, decided from this file's own header. The
    # remaining columns are this client's chart of accounts ("Purchase 18%",
    # "FEE FOR ISO CERTIFICATION", "Legal Expenses@18%") and are never read --
    # they differ for every company.
    tax_cols = [(c, _tax_kind(n)) for c, n in header_row.items() if n and _TAX_COL.match(n.strip())]
    if not tax_cols:
        raise ValueError(f"no GST columns found in {sheet!r}; header was {header_row}")

    header_seen = False
    out = []
    for i, r in enumerate(rows):
        if r is header_row:
            header_seen = True
            continue
        if not header_seen:
            continue
        vtype = (r.get(by_field["voucher_type"]) or "").strip().lower()
        if "purchase" not in vtype:
            continue
        gstin = (r.get(by_field["gstin"]) or "").strip().upper()
        date_raw = r.get(by_field["date"])
        if not gstin or not date_raw:
            continue

        # Tax from the GST columns themselves. Deriving it as
        # (Gross - Value) looked right and was wrong: for service purchases
        # Tally leaves Value blank and puts the base in the expense ledger, so
        # the whole invoice total was being reported as tax. See INCIDENTS #5.
        parts = {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
        for col, kind in tax_cols:
            parts[kind] += _f(r.get(col))
        gross = _f(r.get(by_field["gross_total"]))
        tax = round(sum(parts.values()), 2)

        out.append(
            Invoice(
                gstin=gstin,
                supplier=(r.get(by_field["supplier"]) or "").strip(),
                inv_no=(r.get(by_field["inv_no"]) or "").strip(),
                inv_date=excel_serial_to_date(date_raw),
                taxable=round(gross - tax, 2),
                igst=round(parts["igst"], 2),
                cgst=round(parts["cgst"], 2),
                sgst=round(parts["sgst"], 2),
                cess=round(parts["cess"], 2),
                source="TALLY",
                row_id=f"TALLY{i:06d}",
            )
        )
    if not out:
        raise ValueError(f"parsed 0 purchase rows from {path} -- header matched but no data rows found")
    return out
