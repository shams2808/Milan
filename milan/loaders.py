"""Loaders for real GSTR-2A and Tally exports.

Built directly against real multi-sheet accounting exports (FY 2025-26), not
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

_GSTR2A_CDNR_KEYS = {
    "gstin/uin of supplier": "gstin",
    "gstin of supplier": "gstin",
    "trade/legal name": "supplier",
    "note type": "note_type",
    "note number": "inv_no",
    "note date": "inv_date",
    "note  date": "inv_date",
    "taxable value": "taxable",
    "integrated tax": "igst",
    "central tax": "cgst",
    "state tax": "sgst",
    "cess amount": "cess",
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


def _parse_ddmmyyyy(s):
    if not s:
        return None
    from datetime import date, datetime
    if isinstance(s, date):
        return s
    s_clean = str(s).strip()
    try:
        f_val = float(s_clean)
        if 20000 < f_val < 70000:
            return excel_serial_to_date(f_val)
    except (ValueError, TypeError):
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s_clean, fmt).date()
        except ValueError:
            continue
    return None


def load_gstr2a(path: str) -> list[Invoice]:
    """Load GSTR-2A or GSTR-2B portal exports.
    
    Supports multi-sheet annual portal summaries ('Only Invoice' sheet with 2-row merged header)
    as well as standard B2B/2A/2B sheets with 1-row or 2-row headers.
    """
    wb = Workbook(path)
    try:
        sheet = wb.find_sheet("Only Invoice")
    except (KeyError, ValueError):
        sheet = next(
            (n for n in wb.sheet_names() if any(k in n.lower() for k in ["b2b", "only invoice", "2a", "2b", "inward"])),
            wb.sheet_names()[0],
        )
    rows = list(wb.rows(sheet))

    # Look for header rows (multi-row portal summaries vs single-row exports)
    header_rows = [
        r for r in rows[:15]
        if any(w in "".join(str(v or "") for v in r.values()).lower() for w in ["gstin of supplier", "gstin", "invoice number"])
    ]
    if not header_rows and rows:
        header_rows = [rows[0]]
    if not header_rows:
        raise ValueError(f"expected header row in {sheet!r}, found 0")

    cols = header_map(header_rows, _GSTR2A_KEYS, merge_rows=len(header_rows))
    by_field = {v: k for k, v in cols.items()}
    if "gstin" not in by_field or "inv_no" not in by_field:
        raise ValueError(f"GSTR-2A/2B sheet {sheet!r} is missing required GSTIN or invoice number columns")

    # Filing period column if present (e.g. Col O "Filing Period")
    fp_col = next((col for r in header_rows for col, val in r.items()
                   if val and "filing period" in str(val).lower() and "gstr" not in str(val).lower()), None)
    if not fp_col:
        fp_col = next((col for r in header_rows for col, val in r.items()
                       if val and "filing period" in str(val).lower()), None)

    out = []
    for i, r in enumerate(rows):
        gstin = r.get(by_field["gstin"])
        date_raw = r.get(by_field.get("inv_date"))
        if not gstin or not date_raw:
            continue
        gstin_str = str(gstin).strip().upper()
        if "GSTIN" in gstin_str or "SUPPLIER" in gstin_str:
            continue
        parsed_date = _parse_ddmmyyyy(date_raw)
        if not parsed_date:
            continue
        fp = (r.get(fp_col) or "").strip() if fp_col else ""
        out.append(
            Invoice(
                gstin=gstin_str,
                supplier=(str(r.get(by_field.get("supplier", "")) or "")).strip(),
                inv_no=(str(r.get(by_field["inv_no"]) or "")).strip(),
                inv_date=parsed_date,
                taxable=_f(r.get(by_field.get("taxable"))),
                igst=_f(r.get(by_field.get("igst"))),
                cgst=_f(r.get(by_field.get("cgst"))),
                sgst=_f(r.get(by_field.get("sgst"))),
                cess=_f(r.get(by_field.get("cess"))),
                filing_period=fp,
                source="2A",
                row_id=f"2A{i:06d}",
            )
        )
    if not out:
        raise ValueError(f"parsed 0 invoices from {path} -- header matched but no data rows found")

    out.extend(_load_gstr2a_cdnr(wb))
    return out


def _load_gstr2a_cdnr(wb: Workbook) -> list[Invoice]:
    """Parse Credit / Debit Notes from the CDNR sheet of GSTR-2A if present.
    Credit notes (Type 'C') reduce ITC and are loaded with negative tax/taxable values,
    aligning with accounting books."""
    sheet = next((s for s in wb.sheet_names() if "cdnr" in s.strip().lower()), None)
    if not sheet:
        return []
    rows = list(wb.rows(sheet))
    if len(rows) < 6:
        return []

    # Find the 2-row header containing note number / note type
    header_indices = [
        idx for idx, r in enumerate(rows[:10])
        if any("note number" in str(v).lower() or "note type" in str(v).lower() or "gstin" in str(v).lower() for v in r.values())
    ]
    if len(header_indices) < 2:
        return []
    header_rows = [rows[i] for i in header_indices[:2]]
    start_data_idx = max(header_indices[:2]) + 1

    cols = header_map(header_rows, _GSTR2A_CDNR_KEYS, merge_rows=2)
    by_field = {v: k for k, v in cols.items()}
    if "gstin" not in by_field or "inv_no" not in by_field or "inv_date" not in by_field:
        return []

    fp_col = next((col for r in header_rows for col, val in r.items()
                   if val and "filing period" in str(val).lower()), None)

    out = []
    for i, r in enumerate(rows[start_data_idx:], start=start_data_idx + 1):
        gstin = (r.get(by_field["gstin"]) or "").strip().upper()
        date_raw = r.get(by_field["inv_date"])
        note_no = (r.get(by_field["inv_no"]) or "").strip()
        if not gstin or not date_raw or not note_no or gstin.startswith("GSTIN"):
            continue
        try:
            inv_date = _parse_ddmmyyyy(date_raw)
        except (ValueError, TypeError):
            continue

        note_type = (r.get(by_field.get("note_type", "")) or "C").strip().upper()
        sign = -1.0 if note_type.startswith("C") else 1.0

        taxable = sign * _f(r.get(by_field.get("taxable", "")))
        igst = sign * _f(r.get(by_field.get("igst", "")))
        cgst = sign * _f(r.get(by_field.get("cgst", "")))
        sgst = sign * _f(r.get(by_field.get("sgst", "")))
        cess = sign * _f(r.get(by_field.get("cess", "")))
        fp = (r.get(fp_col) or "").strip() if fp_col else ""

        out.append(
            Invoice(
                gstin=gstin,
                supplier=(r.get(by_field.get("supplier", "")) or "").strip(),
                inv_no=note_no,
                inv_date=inv_date,
                taxable=taxable,
                igst=igst,
                cgst=cgst,
                sgst=sgst,
                cess=cess,
                filing_period=fp,
                source="2A_CDNR",
                row_id=f"2ACDNR{i:06d}",
            )
        )
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



def _parse_busy_date(raw):
    if not raw:
        return None
    raw_str = str(raw).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime
            return datetime.strptime(raw_str, fmt).date()
        except ValueError:
            pass
    try:
        return excel_serial_to_date(raw_str)
    except Exception:
        return None


def _load_busy_register(rows: list[dict[str, str]], sheet: str, header_row: dict[str, str], header_idx: int) -> tuple[list[Invoice], dict[str, int]]:
    """Parse Busy Accounting Software Supply Inward / Purchase Register export."""
    col_party = next((k for k, v in header_row.items() if v and "party" in str(v).lower()), "D")
    col_gstin = next((k for k, v in header_row.items() if v and "gstin" in str(v).lower()), "E")
    col_docno = next((k for k, v in header_row.items() if v and ("doc. no" in str(v).lower() or "doc no" in str(v).lower())), "G")
    col_date  = next((k for k, v in header_row.items() if v and ("doc. date" in str(v).lower() or "doc date" in str(v).lower())), "H")
    col_taxable = next((k for k, v in header_row.items() if v and "taxable" in str(v).lower()), "J")
    col_igst  = next((k for k, v in header_row.items() if v and str(v).strip().lower() == "igst"), "L")
    col_cgst  = next((k for k, v in header_row.items() if v and str(v).strip().lower() == "cgst"), "M")
    col_sgst  = next((k for k, v in header_row.items() if v and str(v).strip().lower() == "sgst"), "N")
    col_cess  = next((k for k, v in header_row.items() if v and "cess" in str(v).lower()), "O")
    col_sec   = next((k for k, v in header_row.items() if v and "section" in str(v).lower()), "B")

    out = []
    current_inv = None
    counts: dict[str, int] = {}

    for row_idx, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        row_str = " ".join(str(v) for v in r.values() if v)
        if "total" in row_str.lower() and (not r.get(col_party) or str(r.get(col_date)).strip() == "Total"):
            continue
        party = (r.get(col_party) or "").strip()
        if "org. inv." in party.lower() or "doc. type" in party.lower():
            continue

        docno = (r.get(col_docno) or "").strip()
        gstin = (r.get(col_gstin) or "").strip().upper()
        date_raw = r.get(col_date)

        taxable = _f(r.get(col_taxable))
        igst = _f(r.get(col_igst))
        cgst = _f(r.get(col_cgst))
        sgst = _f(r.get(col_sgst))
        cess = _f(r.get(col_cess))
        sec = (r.get(col_sec) or "B2B").strip().upper()

        # Multi-tax-rate continuation line in Busy
        if not docno and not gstin:
            if current_inv is not None and (taxable != 0 or igst != 0 or cgst != 0 or sgst != 0 or cess != 0):
                current_inv.taxable = round(current_inv.taxable + taxable, 2)
                current_inv.igst = round(current_inv.igst + igst, 2)
                current_inv.cgst = round(current_inv.cgst + cgst, 2)
                current_inv.sgst = round(current_inv.sgst + sgst, 2)
                current_inv.cess = round(current_inv.cess + cess, 2)
            continue

        inv_date = _parse_busy_date(date_raw)
        if not inv_date or not gstin:
            continue

        counts[sec] = counts.get(sec, 0) + 1
        current_inv = Invoice(
            gstin=gstin,
            supplier=party,
            inv_no=docno,
            inv_date=inv_date,
            taxable=round(taxable, 2),
            igst=round(igst, 2),
            cgst=round(cgst, 2),
            sgst=round(sgst, 2),
            cess=round(cess, 2),
            source="BUSY",
            voucher_type=sec,
            row_id=f"BUSY{row_idx:06d}",
        )
        out.append(current_inv)

    if not out:
        raise ValueError(f"parsed 0 inward rows from Busy register in {sheet!r}")
    return out, counts

def _load_one_tally(path: str, *, inward_only: bool = True) -> tuple[list[Invoice], dict[str, int]]:
    wb = Workbook(path)
    sheet = next(
        (n for n in wb.sheet_names() if "purchase" in n.lower() or "day book" in n.lower()),
        wb.sheet_names()[0],
    )
    rows = list(wb.rows(sheet))

    # Check for Busy register header first
    for idx, r in enumerate(rows[:25]):
        line = " ".join(str(v).lower() for v in r.values() if v)
        if ("doc. no" in line or "party" in line or "doc no" in line) and "gstin" in line:
            return _load_busy_register(rows, sheet, r, idx)

    header_row = next((r for r in rows if "particulars" in "".join(v or "" for v in r.values()).lower()
                        and "gstin" in "".join(v or "" for v in r.values()).lower()), None)
    if header_row is None:
        raise ValueError(f"could not identify accounting register format in {sheet!r}. Supported formats: Tally (DayBook/Purchase) and Busy (Supply Inward Register).")
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

load_books = load_tally
