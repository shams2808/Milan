"""Milan -- annual GST ITC reconciliation, real client files.

    python -m milan.real <gstr2a.xlsx> <tally_purchase.xlsx>

No ground truth exists for real data, so there is no accuracy section here --
only the reconciliation itself. Everything this prints is a real number about
a real client; it is not meant to leave the machine it runs on.
"""

from __future__ import annotations

import argparse

from .export import write_csv
from .loaders import load_gstr2a, load_tally_purchase
from .match import reconcile
from .report import print_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gstr2a", help="GSTR-2A annual summary .xlsx from the portal")
    ap.add_argument("tally", help="Tally Purchase Register .xlsx export")
    ap.add_argument("--show", type=int, default=8, help="rows per section")
    ap.add_argument("--csv", help="write every finding to this CSV for Excel")
    args = ap.parse_args()

    gstr = load_gstr2a(args.gstr2a)
    tally = load_tally_purchase(args.tally)
    res = reconcile(tally, gstr)

    print(f"\nMilan -- ITC reconciliation")
    print(f"GSTR-2A : {args.gstr2a}")
    print(f"Tally   : {args.tally}\n")
    print_report(tally, gstr, res, show=args.show)

    if args.csv:
        n = write_csv(args.csv, tally, gstr, res)
        print(f"\n{n} findings written to {args.csv}")
    print()


if __name__ == "__main__":
    main()
