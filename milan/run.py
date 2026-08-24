"""Milan -- annual GST ITC reconciliation, synthetic eval.

    python -m milan.run              # full synthetic year
    python -m milan.run --n 300

Reports the two piles a tax practitioner actually needs at year end:
    in Tally, not in 2A  ->  ITC claimed that was never available (reverse it)
    in 2A, not in Tally  ->  ITC available the client never claimed (expires)

For a reconciliation on real files, see `python -m milan.real`.
"""

from __future__ import annotations

import argparse

from .match import reconcile
from .report import evaluate, print_report
from .synth import build_year


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--show", type=int, default=5, help="rows per section")
    args = ap.parse_args()

    tally, gstr, planted = build_year(n_invoices=args.n, seed=args.seed)
    res = reconcile(tally, gstr)

    print("\nMilan -- FY 2025-26 ITC reconciliation (SYNTHETIC)")
    print_report(tally, gstr, res, show=args.show)

    ev = evaluate(res, planted)
    print(f"\n{'-' * 74}")
    print("measured accuracy against ground truth (synthetic year)")
    print(f"  precision {ev['precision']:.3%}   recall {ev['recall']:.3%}   "
          f"wrong matches {ev['wrong']}")
    print(f"  planted: {planted}")
    print("\nThis run is synthetic data. For the real client run, see milan.real.\n")


if __name__ == "__main__":
    main()
