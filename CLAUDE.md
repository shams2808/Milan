# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Milan** (मिलान — the word a tax practitioner uses for reconciliation) does annual
GST input-tax-credit reconciliation: GSTR-2A from the portal against a Tally
purchase register, for a full financial year. Built for the Razorpay AI Buildathon
2026, Track 04.

The problem was chosen by a practising tax advocate and his colleague, not invented.
Their framing drives the whole design: find invoices in Tally but not in 2A (ITC
claimed that was never available → reverse + interest u/s 50) and invoices in 2A but
not in Tally (ITC available never claimed → lapses 30 Nov under s.16(4)).

## Commands

```bash
python -m milan.test_milan     # self-check, 13 assertions, no pytest
python -m milan.run --n 1200   # synthetic year with ground truth + precision/recall
python -m milan.real <gstr2a.xlsx> <tally.xlsx> [more_tally.xlsx ...] --csv out.csv
```

Run a single test: there is no runner, so call it directly —
`python -c "from milan.test_milan import test_never_matches_across_gstin as t; t()"`

**Zero dependencies, standard library only.** There is no requirements.txt and there
should not be one. `xlsx_lite.py` exists specifically so that reading .xlsx does not
pull in openpyxl. Do not add a dependency without a strong reason.

On Windows, prefix with `PYTHONIOENCODING=utf-8` — the report prints ₹ and en-dashes
that cp1252 cannot encode.

## Architecture

Data flows one direction, and each stage is separately testable:

```
loaders.py   real .xlsx  ->  Invoice
synth.py     fake year   ->  Invoice + truth_id      (ground truth for eval)
     |
match.py     GSTIN-blocked deterministic cascade  -> Result(pairs, only_tally, only_gstr, review)
     |
report.py    Result -> two piles, each split BY CAUSE
export.py    Result -> flat CSV, one row per finding
blocked.py   Invoice -> s.17(5) Flag (advisory only)
```

`run.py` (synthetic) and `real.py` (real files) are thin entrypoints that share
`report.print_report`. Only the synthetic path has ground truth, so only it prints
precision/recall.

### The two invariants everything rests on

**1. GSTIN is an exact blocking key.** The practitioner's rule, verbatim: *"GST number
should be same."* The matcher never compares invoices across suppliers. Two GSTINs
sharing a PAN are the same legal entity in different states (Ingram Micro bills from
27… and 06…) — still never auto-matched, because different registrations are legally
different suppliers. They are reported as a books correction via `report.pan_conflicts`.

**2. Precision beats recall.** A false match wrongly claims ITC and draws interest
under s.50. A missed match only lands on a human's review list. When a cascade stage
finds several equally good candidates it refuses to guess and pushes the row to
`Result.review` with its candidates attached.

### The matching cascade (`match.py`)

Strongest first, one-to-one, inside one GSTIN. A weaker stage can never overturn a
stronger one. Every near-miss stage requires tax **and** date to agree, so a
near-miss invoice number can never carry a match on its own.

`exact` → `format_variant` → `amount_mismatch` → `supplier_code` → `typo_in_number`
→ `value_and_date`

Two normalisation tiers in `core.py`: `norm_strict` (loses nothing) and `norm_loose`
(strips financial-year markers and document-type prefixes). Matching tries strict
first so loose can never override a confident answer.

`norm_loose` is **token-based on purpose**. A regex over the raw string matched
`06/25` *inside* `006/25-26` and collapsed three distinct invoices onto one key.
Do not "simplify" it back to a regex.

## Where AI is used, and where it deliberately is not

This is a stated design position, not an accident, and it is a judged criterion of
the buildathon. **No LLM ever asserts that two invoices are the same** — matching an
invoice wrong moves a real ITC claim.

Rules-first everywhere they reach: classification is a lookup, not a judgement.
The LLM's place is the residual where a supplier's trade name genuinely does not say
what was sold (`blocked.unflagged_suppliers` is that queue, and
`blocked.LLM_PROMPT` requires abstention over guessing). When wired, it may only
choose among candidates the deterministic cascade already proposed.

`blocked.py` flags possible s.17(5) blocked credits but **never excludes anything
from a total**. Whether a credit is blocked turns on facts these files do not contain
— whether a repair was capitalised, whether insurance was obligatory. Each rule
carries its statutory exception because the exception usually decides the case. The
tool narrows thousands of invoices to a handful; the advocate rules.

## Reporting rule: never print one undifferentiated number

The first real run reported "542 invoices in 2A but not in Tally." Arithmetically
correct, diagnostically useless — it was four unrelated situations summed together,
and only 93 were genuinely unclaimed. An undifferentiated pile is exactly what
existing tools produce and what the practitioner then redoes by hand. His complaint
about the tool he uses: *"shows the differences but complicates them a lot."*

So both piles are split by cause, each bucket states its own action, and the bottom
line separates "claim this," "reverse this," "fix the ledger," and "cannot verify
from these files."

## Working with real data

Client files live in `milan/Data/` and are **gitignored — never commit them.** They
are live financial records of a real business, and filenames may contain a real
GSTIN. Check `git ls-files --cached | grep -i Data/` before pushing.

Known scope limit: a Tally **Purchase Register contains only Purchase vouchers**,
while GSTR-2A contains every inward supply. Expenses (bank charges, insurance, air
tickets, platform fees) are booked as Journal/Payment vouchers and cannot appear.
`load_tally()` therefore accepts several register exports and merges them. Never
report that gap as unclaimed ITC — it is unverified, which is a different claim.

## Testing philosophy

Every bug in `INCIDENTS.md` was found by **making the test data harder, never by
reading the code**. Two separate green runs were worth nothing: a 99.9% score hid two
normaliser bugs (unique float amounts silently rescued mangled matches), and a later
100%/100% only proved the generator and matcher shared an author's blind spots.

Read `INCIDENTS.md` before trusting any accuracy number here. When the eval looks
too good, the correct move is to inject a failure mode you have deliberately not
built for — not to write it up as a result.

Most tests in `test_milan.py` encode a bug that actually shipped. Keep it that way:
when you fix something real, leave a test that fails if it returns.
