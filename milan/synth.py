"""A synthetic financial year, with ground truth.

Real files arrive from the practitioner on 1 September. Until then this stands
in. Every distortion below was named by a practising tax advocate or appears in
published ITC-reconciliation guidance -- none of it is invented for effect:

  * the same invoice numbered differently on the two sides (the core problem)
  * supplier never filed GSTR-1, so the invoice never reaches 2A
  * client never booked an invoice that is sitting in 2A
  * tax value differing by rounding, or by a real error
  * supplier filing late, so 2A shows a later period than the books
  * the client booking the same purchase twice
  * a GSTIN mistyped in Tally, which breaks the blocking key entirely

`truth_id` is written onto both sides of a genuine pair so eval.py can score
the matcher. The matcher never reads it.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .core import Invoice

FY_MONTHS = [(2025, m) for m in range(4, 13)] + [(2026, m) for m in range(1, 4)]

_STYLES = [
    lambda n, fy: f"INV/{fy}/{n:04d}",
    lambda n, fy: f"{n}",
    lambda n, fy: f"BILL-{n:03d}",
    lambda n, fy: f"GST{n:05d}",
    lambda n, fy: f"{n:04d}",
    lambda n, fy: f"INV-{fy[2:]}-{n}",
    lambda n, fy: f"{n:03d}/{fy[2:]}",
]

_STATES = ["27", "07", "29", "33", "24", "19", "06", "36"]


def _gstin(rng: random.Random) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    pan = (
        "".join(rng.choice(letters) for _ in range(3))
        + rng.choice("CPHFAT")
        + rng.choice(letters)
        + f"{rng.randint(0, 9999):04d}"
        + rng.choice(letters)
    )
    return f"{rng.choice(_STATES)}{pan}{rng.randint(1, 9)}Z{rng.choice(letters)}"


def _name(rng: random.Random) -> str:
    a = ["Shree", "Bharat", "Nova", "Vikram", "Ganesh", "Apex", "Deccan", "Surya",
         "Krishna", "Metro", "Prime", "Sagar", "Anand", "Rajdhani", "Vertex"]
    b = ["Traders", "Industries", "Enterprises", "Steel", "Textiles", "Agencies",
         "Chemicals", "Packaging", "Logistics", "Supplies", "Polymers"]
    c = ["Pvt Ltd", "LLP", "& Co", "Ltd", ""]
    return " ".join(x for x in (rng.choice(a), rng.choice(b), rng.choice(c)) if x)


def _amounts(rng: random.Random) -> dict:
    taxable = round(rng.choice([1, 1, 1, 10]) * rng.uniform(800, 90000), 2)
    rate = rng.choice([0.05, 0.12, 0.18, 0.18, 0.18, 0.28])
    tax = round(taxable * rate, 2)
    if rng.random() < 0.55:  # inter-state
        return dict(taxable=taxable, igst=tax)
    half = round(tax / 2, 2)
    return dict(taxable=taxable, cgst=half, sgst=round(tax - half, 2))


def _period(y: int, m: int, shift: int = 0) -> str:
    m0 = m - 1 + shift
    return f"{y + m0 // 12}-{m0 % 12 + 1:02d}"


def build_year(n_suppliers: int = 45, n_invoices: int = 1200, seed: int = 3):
    """Returns (tally_rows, gstr2a_rows, planted) where planted is a summary
    of exactly what was injected, so eval.py can check we found it."""
    rng = random.Random(seed)
    # A quarter of suppliers bill an identical amount every month -- rent,
    # retainers, AMCs, subscriptions. Without these the synthetic amounts are
    # near-unique floats and the value+date matching stage looks far more
    # reliable than it can possibly be on real books. See INCIDENTS.md #1.
    suppliers = []
    for _ in range(n_suppliers):
        recurring = _amounts(rng) if rng.random() < 0.25 else None
        suppliers.append((_gstin(rng), _name(rng), rng.randrange(len(_STYLES)), recurring))

    tally: list[Invoice] = []
    gstr: list[Invoice] = []
    planted = dict(pairs=0, only_tally=0, only_gstr=0, amount_mismatch=0,
                   cross_period=0, duplicate=0, wrong_gstin=0, format_variant=0,
                   supplier_prefix=0, blank_invno=0, transposed=0)

    counters: dict[str, int] = {}

    for i in range(n_invoices):
        gstin, name, style_ix, recurring = rng.choice(suppliers)
        y, m = rng.choice(FY_MONTHS)
        d = date(y, m, rng.randint(1, 28))
        fy = "2025-26"
        counters[gstin] = counters.get(gstin, 0) + 1
        seq = counters[gstin]
        amt = dict(recurring) if recurring else _amounts(rng)
        tid = f"T{i:05d}"

        gstr_no = _STYLES[style_ix](seq, fy)
        roll = rng.random()

        # The client books it, writing the number in whatever style they like.
        if rng.random() < 0.40:
            other = rng.randrange(len(_STYLES))
            tally_no = _STYLES[other](seq, fy)
            if tally_no != gstr_no:
                planted["format_variant"] += 1
        else:
            tally_no = gstr_no

        def mk(source, inv_no, period, extra=None, gst=gstin):
            a = dict(amt)
            if extra:
                a.update(extra)
            return Invoice(
                gstin=gst, supplier=name, inv_no=inv_no, inv_date=d,
                period=period, source=source,
                row_id=f"{source}{i:05d}", truth_id=tid, **a,
            )

        book_period = _period(y, m)

        if roll < 0.06:                      # supplier never filed
            tally.append(mk("TALLY", tally_no, book_period))
            planted["only_tally"] += 1
        elif roll < 0.12:                    # client never booked it
            gstr.append(mk("2A", gstr_no, book_period))
            planted["only_gstr"] += 1
        elif roll < 0.15:                    # tax differs
            off = rng.choice([-50, -12.5, 18, 240, 1000])
            key = "igst" if amt.get("igst") else "cgst"
            tally.append(mk("TALLY", tally_no, book_period,
                            {key: round(amt[key] + off, 2)}))
            gstr.append(mk("2A", gstr_no, book_period))
            planted["amount_mismatch"] += 1
            planted["pairs"] += 1
        elif roll < 0.17:                    # supplier filed late
            tally.append(mk("TALLY", tally_no, book_period))
            gstr.append(mk("2A", gstr_no, _period(y, m, rng.randint(1, 2))))
            planted["cross_period"] += 1
            planted["pairs"] += 1
        elif roll < 0.19:                    # booked twice
            tally.append(mk("TALLY", tally_no, book_period))
            dup = mk("TALLY", tally_no, book_period)
            dup.row_id = f"TALLYD{i:05d}"
            tally.append(dup)
            gstr.append(mk("2A", gstr_no, book_period))
            planted["duplicate"] += 1
            planted["pairs"] += 1
        elif roll < 0.23:                    # 2A carries a supplier code, books don't
            code = "".join(w[0] for w in name.split()[:3]).upper()
            tally.append(mk("TALLY", tally_no, book_period))
            gstr.append(mk("2A", f"{code}/{gstr_no}", book_period))
            planted["supplier_prefix"] += 1
            planted["pairs"] += 1
        elif roll < 0.25:                    # bulk journal entry, no invoice no.
            tally.append(mk("TALLY", "", book_period))
            gstr.append(mk("2A", gstr_no, book_period))
            planted["blank_invno"] += 1
            planted["pairs"] += 1
        elif roll < 0.27:                    # digits transposed while typing
            digits = [c for c in tally_no if c.isdigit()]
            if len(digits) >= 2:
                a, b = tally_no.rfind(digits[-2]), tally_no.rfind(digits[-1])
                lst = list(tally_no); lst[a], lst[b] = lst[b], lst[a]
                typo = "".join(lst)
            else:
                typo = tally_no
            tally.append(mk("TALLY", typo, book_period))
            gstr.append(mk("2A", gstr_no, book_period))
            planted["transposed"] += 1
            planted["pairs"] += 1
        elif roll < 0.28:                    # GSTIN mistyped in the books
            bad = gstin[:6] + rng.choice("0123456789") + gstin[7:]
            tally.append(mk("TALLY", tally_no, book_period, gst=bad))
            gstr.append(mk("2A", gstr_no, book_period))
            planted["wrong_gstin"] += 1
        else:                                # ordinary clean pair
            tally.append(mk("TALLY", tally_no, book_period))
            gstr.append(mk("2A", gstr_no, book_period))
            planted["pairs"] += 1

    rng.shuffle(tally)
    rng.shuffle(gstr)
    return tally, gstr, planted
