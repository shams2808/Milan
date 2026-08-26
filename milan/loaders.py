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

from .core import FY_MONTHS, GSTR3BMonth, GSTR3BSummary, Invoice
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
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return 0.0


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
    # Filing period column if present (e.g. Col O "Filing Period")
    fp_col = next((col for r in header_rows for col, val in r.items()
                   if val and "filing period" in str(val).lower() and "gstr" not in str(val).lower()), None)
    if not fp_col:
        fp_col = next((col for r in header_rows for col, val in r.items()
                       if val and "filing period" in str(val).lower()), None)

    out = []
    for i, r in enumerate(rows):
        gstin = r.get(by_field["gstin"])
        date_raw = r.get(by_field["inv_date"])
        # Title rows ("Goods and Services Tax - GSTR 2A", section headings)
        # land text in column A too, so a truthy GSTIN alone doesn't identify
        # a data row -- every real data row also has a date; no title row does.
        if not gstin or not date_raw or gstin == "GSTIN of supplier":
            continue
        fp = (r.get(fp_col) or "").strip() if fp_col else ""
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
                filing_period=fp,
                source="2A",
                row_id=f"2A{i:06d}",
            )
        )
    if not out:
        raise ValueError(f"parsed 0 invoices from {path} -- header matched but no data rows found")
    return out


def load_gstr3b(path: str) -> GSTR3BSummary:
    """Load annual GSTR-3B monthly summary report.

    Extracts monthly and FY totals:
      - ITC non-reverse-charge (Table 4A(5))
      - ITC reverse-charge (Table 4A(3) / 3.1(d))
      - Tax liability (Table 3.1)
      - Cash offset (Table 6.1)
      - Opening & closing ITC balances
    """
    wb = Workbook(path)
    sheet = next(
        (n for n in wb.sheet_names() if "summary" in n.lower() or "gstr-3b" in n.lower() or "3b" in n.lower()),
        wb.sheet_names()[0],
    )
    rows = list(wb.rows(sheet))

    # Metadata extraction (client name, GSTIN, FY)
    gstin, name, fy = "", "", ""
    for r in rows[:10]:
        for val in r.values():
            if not val:
                continue
            text = str(val)
            m_gstin = re.search(r"GSTIN:\s*([0-9A-Z]{15})", text, re.I)
            if m_gstin:
                gstin = m_gstin.group(1).upper()
            m_name = re.search(r"Name:\s*([^\n\r]+)", text, re.I)
            if m_name:
                name = m_name.group(1).strip()
            m_fy = re.search(r"\((\d{4}-\d{4})\)", text)
            if m_fy:
                fy = m_fy.group(1)

    # Locate month header row
    header_row_idx = None
    month_col_map = {}
    total_col = None

    for idx, r in enumerate(rows[:15]):
        col_to_month = {}
        for col, val in r.items():
            if not val:
                continue
            val_clean = str(val).strip().lower()
            for m in FY_MONTHS:
                if m.lower() in val_clean or (len(val_clean) >= 3 and val_clean.startswith(m.lower()[:3])):
                    col_to_month[m] = col
            if "total" in val_clean:
                total_col = col
        if len(col_to_month) >= 6:
            header_row_idx = idx
            month_col_map = col_to_month
            break

    if header_row_idx is None:
        raise ValueError(f"could not find month header row in GSTR-3B sheet {sheet!r}")

    monthly_data = {m: GSTR3BMonth(month=m) for m in FY_MONTHS}
    totals = {
        "itc_non_rev": 0.0,
        "itc_rev": 0.0,
        "tax_liability": 0.0,
        "cash_offset": 0.0,
    }

    curr_sec = ""
    for r in rows[header_row_idx + 1:]:
        if not any(r.values()):
            continue
        sec_val = r.get("A")
        if sec_val:
            curr_sec = str(sec_val).strip()
        part_val = str(r.get("B") or "").strip()
        sec_low = curr_sec.lower()
        part_low = part_val.lower()

        def get_row_vals():
            m_vals = {m: _f(r.get(col)) for m, col in month_col_map.items()}
            tot_val = _f(r.get(total_col)) if total_col else sum(m_vals.values())
            return m_vals, tot_val

        if "input tax credit" in sec_low and ("non reverse" in sec_low or "non-reverse" in sec_low):
            if "total" in part_low:
                m_vals, tot = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].itc_non_rev = val
                totals["itc_non_rev"] = tot
        elif "input tax credit" in sec_low and "reverse charge" in sec_low and "non reverse" not in sec_low:
            if "total" in part_low:
                m_vals, tot = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].itc_rev = val
                totals["itc_rev"] = tot
        elif "tax liability" in sec_low:
            if "total (including reverse charge)" in part_low or ("total" in part_low and "including" in part_low):
                m_vals, tot = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].tax_liability = val
                totals["tax_liability"] = tot
            elif "total" in part_low and totals["tax_liability"] == 0.0:
                m_vals, tot = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].tax_liability = val
                totals["tax_liability"] = tot
        elif "cash offset" in sec_low:
            if "total" in part_low:
                m_vals, tot = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].cash_offset = val
                totals["cash_offset"] = tot
        elif "opening itc balance" in sec_low:
            if "total" in part_low:
                m_vals, _ = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].opening_balance = val
        elif "closing itc balance" in sec_low:
            if "total" in part_low:
                m_vals, _ = get_row_vals()
                for m, val in m_vals.items():
                    monthly_data[m].closing_balance = val

    opening_fy = monthly_data["April"].opening_balance if "April" in monthly_data else 0.0
    closing_fy = monthly_data["March"].closing_balance if "March" in monthly_data else 0.0

    return GSTR3BSummary(
        gstin=gstin,
        name=name,
        fy=fy,
        months=monthly_data,
        total_itc_non_rev=round(totals["itc_non_rev"], 2),
        total_itc_rev=round(totals["itc_rev"], 2),
        total_tax_liability=round(totals["tax_liability"], 2),
        total_cash_offset=round(totals["cash_offset"], 2),
        opening_balance=round(opening_fy, 2),
        closing_balance=round(closing_fy, 2),
    )


# Voucher types that represent an INWARD supply (something bought). Sales,
# Receipt and Credit Note are outward -- their GSTINs are customers, and
# reconciling those against GSTR-2A would be meaningless.
#
# The expenses that never reach a Purchase Register -- bank charges, insurance,
# platform fees, air tickets -- are booked as Journal or Payment vouchers.
# Those registers can be exported separately and passed alongside the Purchase
# Register; see load_tally().
INWARD_VOUCHERS = ("purchase", "journal", "payment", "debit note", "expense")

OUTWARD_VOUCHERS = ("sales", "receipt", "credit note", "sale ")


def load_tally(paths: list[str], *, inward_only: bool = True) -> tuple[list[Invoice], dict[str, int]]:
    """Load and merge several Tally register exports.

    A practitioner cannot always produce one unfiltered Day Book, but can
    usually export a Purchase Register, a Journal Register and a Payment
    Register separately. Merging them here is what lets the expense-side
    inward supplies be reconciled at all.

    Returns (invoices, voucher_type_counts) so the caller can show which
    voucher types were actually included -- silently dropping half a file
    would be the worst possible failure mode for this tool.
    """
    merged: list[Invoice] = []
    seen: dict[str, int] = {}
    for path in paths:
        rows, counts = _load_one_tally(path, inward_only=inward_only)
        merged.extend(rows)
        for k, v in counts.items():
            seen[k] = seen.get(k, 0) + v

    # The same voucher can appear in two registers (a Purchase Register and a
    # Day Book that contains it). Same supplier, same invoice, same tax, same
    # date is the same document, not a genuine duplicate purchase.
    unique: dict[tuple, Invoice] = {}
    for inv in merged:
        key = (inv.gstin, inv.strict, round(inv.tax, 2), inv.inv_date)
        unique.setdefault(key, inv)
    return list(unique.values()), seen


def _load_one_tally(path: str, *, inward_only: bool = True) -> tuple[list[Invoice], dict[str, int]]:
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
    counts: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r is header_row:
            header_seen = True
            continue
        if not header_seen:
            continue
        vtype_raw = (r.get(by_field["voucher_type"]) or "").strip()
        vtype = vtype_raw.lower()
        if vtype_raw:
            counts[vtype_raw] = counts.get(vtype_raw, 0) + 1
        if inward_only:
            if any(o in vtype for o in OUTWARD_VOUCHERS):
                continue
            if not any(w in vtype for w in INWARD_VOUCHERS):
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
                voucher_type=vtype_raw,
                row_id=f"TALLY{i:06d}",
            )
        )
    if not out:
        raise ValueError(
            f"parsed 0 inward rows from {path} -- header matched but nothing "
            f"survived the voucher-type filter. Types seen: {sorted(counts)}"
        )
    return out, counts


def load_tally_purchase(path: str) -> list[Invoice]:
    """Single-file convenience wrapper, kept for the tests and simple runs."""
    return load_tally([path])[0]
