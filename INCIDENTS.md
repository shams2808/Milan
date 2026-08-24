# Incidents

What broke and how I got out. Written as it happened. Nothing here is invented.

The through-line: **every real bug was found by making the test harder, not by
reading the code.** Reading the code found nothing. Twice I had a green run
that was worth nothing.

---

## #1 — My eval scored 99.9% while two bugs sat in the matcher

**Day 1.** First full run over a synthetic financial year: precision 99.904%,
recall 99.141%. I nearly wrote it down as the headline.

Two things in the output didn't fit. The review queue said things like
*"8 equally good candidates"* and *"14 equally good candidates"* — but invoice
numbers are unique per supplier, so there should never be more than one. And
`value_and_date` — my weakest, riskiest matching stage, which matches on tax
amount and date when the invoice number is unusable — had fired **154 times**.
A stage that should be a last resort was carrying 15% of the book.

Probing the normaliser directly explained both:

```
006/25-26   -> 26        029/25-26   -> 26        003/25-26   -> 26
GST00006    -> GST00006
```

**Bug one.** My financial-year regex was `(?:20)?\d{2}[-/](?:20)?\d{2}` applied
to the raw string. In `006/25-26` it matched `06/25` — *inside* the invoice
number — leaving `0` + `-26`. Invoices 006, 029 and 003 all collapsed onto the
single key `26`. That is what the review queue had been trying to tell me.

**Bug two.** `\b(INV|BILL|GST|...)\b` never fired on `GST00006`, because there
is no word boundary between `GST` and `00006` — both are word characters. So
that invoice could never match the same invoice written as `6`.

**Why the eval hid it.** My synthetic amounts were `round(uniform(800, 90000) *
rate, 2)` — effectively unique floats. So when the normaliser mangled a number,
`value_and_date` silently rescued the pair on amount alone and scored it
correct. **The eval was measuring my data generator, not my matcher.**

Fixed the normaliser by tokenising first and only removing a year marker when
it is a whole token. Then fixed the generator: a quarter of suppliers now bill
an identical amount every month — rent, retainers, AMCs — which is what real
books look like and what makes amount-only matching dangerous.

---

## #2 — Then it scored 100%, which was also worth nothing

With the normaliser fixed the run came back **100% precision, 100% recall**.

That is not a good result, it is a warning. It means the synthetic data
contains only the distortions I already thought to handle — generator and
matcher written by the same person, same blind spots, same afternoon.

So I injected three failure modes I knew were real and had deliberately *not*
built for: a supplier code on one side only (`SEL/0012` vs `12`), blank invoice
numbers from bulk journal entries, and transposed digits.

Precision fell to 99.615% — **four wrong matches.** Each one was a different
defect:

| Stage | What it matched | Why it was wrong |
|---|---|---|
| `exact` | same number, same tax, **4 months apart** | never sanity-checked the date on the strongest stage |
| `amount_mismatch` ×2 | `GST00020` ↔ `0020`, ₹4,113 vs ₹36,095, 6 months apart | if tax *and* date both disagree, it is not the same document |
| `value_and_date` | `GST00010` ↔ `GST00006` | recurring biller, identical amount; both numbers were perfectly readable and clearly different |

Fixes: a 90-day sanity gap on the strong stages; `amount_mismatch` now requires
the dates to agree; and `value_and_date` only fires when a number is genuinely
*missing*, never to override two readable numbers that disagree.

Wrong matches went to zero — and recall fell to 92.5%. That trade is the right
one here (a false match wrongly claims ITC and draws interest under s.50, while
a missed match only lands on a human's review list) but 78 real pairs were now
polluting the two headline piles. Not acceptable either.

---

## #3 — The fuzzy-matching stage had never matched anything

Chasing that lost recall, I looked at the stage breakdown properly:
`fuzzy_number: 0`. It had **never fired, in any run.**

`difflib.SequenceMatcher.ratio()` on `"12"` vs `"21"` is 0.5, against a floor of
0.85. Invoice numbers normalise down to two or three characters, so a ratio
threshold tuned for prose is meaningless on them. The single commonest typing
error scored the same as a completely unrelated invoice.

Replaced it with two targeted stages — and got the replacement wrong twice more:

1. Wrote plain Levenshtein. Still failed: a transposition costs **2** edits
   (a delete plus an insert), not 1. Needed Damerau-Levenshtein, where an
   adjacent swap costs 1.
2. Wrote `_is_coded` to strip a supplier's alphabetic prefix. It rejected
   `SEL0012` against `12`, because the prefix it tested was `SEL00` — which
   isn't alphabetic. Had to compare the numeric remainder with its leading
   zeros stripped.

With both fixed: **100% precision, 100% recall, 0 wrong matches**, all 1,041
planted pairs recovered.

---

## #4 — The test suite caught the last one, not me

Writing the regression tests, `test_value_and_date_still_rescues_a_blank_number`
failed. A blank invoice number normalises to `"0"` — which is one edit away
from *every* single-character invoice number. My new typo stage was confidently
claiming blank cells as typos of `"6"`.

A missing number is not a typo of anything. Both near-miss stages now require a
real number on each side; blanks fall through to `value_and_date`, which is
what that stage exists for.

---

## Standing caveat

The current 100%/100% carries the same warning as #2. It proves the cascade
handles every distortion I know about. It says nothing about the ones I don't.

Real GSTR-2A and Tally files from a practising tax advocate arrive **1
September**, after his 31 August filing deadline. That is the first honest test
this project will get, and the numbers will move.

---

## #5 — I reported ₹922,513 of "amount mismatches" that were my own arithmetic

**First run on real client files.** 163 invoices came back as "matched but tax
differs," net ₹922,513. The top rows looked absurd:

```
07AAICI4718C1ZR  1/2025-26     books 472,000.00   2A  72,000.00   delta +400,000.00
07AAACS1679N1ZW  815/M         books  45,477.00   2A   6,937.20   delta  +38,539.80
```

Books claiming ₹472,000 of tax where the portal says ₹72,000 is not a
data-entry error, it is a bug. And the delta was suspicious: in every case it
equalled the invoice's *taxable value*.

My Tally loader computed `tax = Gross Total − Value`. That reads correctly and
is correct for a goods purchase. For a **service** purchase Tally leaves the
`Value` column blank and puts the base amount in the expense ledger column
instead:

```
F.A. AIRCON   Gross 20060   CGST 1530   SGST 1530   REPAIRING CHARGE PAID 18%: 17000
```

`Value` is blank, so my loader computed tax = 20060 − 0 = the whole invoice.

The fix was to stop deriving tax at all and sum the actual GST columns,
detected from the header. That needs care: `"Purchase IGST 18%"` is a purchase
*ledger* holding the taxable base, not tax. A substring search for `IGST` would
add the base into the tax and double it. The pattern anchors at the start of
the header instead, so `CGST @9%` matches and `Purchase IGST 18%` does not.

Verified on the real file: `gross == ledgers + tax + round-off` on 1,913 of
1,915 rows (the two exceptions are Tally storing round-off unsigned), and the
resulting tax matches GSTR-2A to the paisa.

Amount mismatches fell from **163 (₹922,513) to 1 (₹72)**. Exact matches rose
from 1,706 to 1,869.

---

## #6 — "542 unclaimed invoices" was four different problems added together

With the tax bug fixed, the report still claimed **542 invoices / ₹2,013,176
sitting in 2A but not in the books**. For a company with 1,913 purchases that
is not credible, and the practitioner's son said so immediately.

Every row was accounted for arithmetically (1874 + 542 = 2418). The failure was
diagnostic: four unrelated situations were being summed into one headline.

Breaking the pile down by *why* each row was unmatched:

| Cause | Invoices | Value |
|---|---|---|
| Supplier absent from the purchase register entirely | **428** | ₹822,537 |
| Supplier is in the books, this invoice is not | 93 | ₹667,342 |
| Same PAN, different GSTIN | 21 | ₹523,297 |

The 428 gave themselves away by name: GOVERNMENT EMARKETPLACE, AMERICAN
AIRLINES, KOTAK MAHINDRA BANK, KOTAK LIFE INSURANCE, SAKSHI 3PL, JAIN TIMBER
TRADERS. 86% carried under ₹2,000 of tax.

Those are **expenses**, not goods purchases — bank charges, insurance, air
tickets, platform fees, freight. Tally books them as Journal or Payment
vouchers. A **Purchase Register export contains only Purchase vouchers**, while
GSTR-2A contains every inward supply. I had been comparing the whole against a
subset and calling the difference unclaimed credit.

The 21 were a second, separate bug: Ingram Micro bills from `27AABCT1296R1ZN`
and `06AABCT1296R1ZR` — one PAN, two state registrations. My GSTIN-typo check
only caught differences of 1–2 characters; a second state registration differs
in three. Added a PAN-level conflict report (still never auto-matching across
GSTINs — different registrations are legally different suppliers).

**What changed.** The report no longer prints one number. Each pile is split by
cause, each bucket says what to actually do, and the honest bottom line is:

```
  ITC confirmed against 2A           Rs 55,427,570
  Claim before 30 Nov (98d)            Rs 667,342   [2a]
  Reverse or chase supplier              Rs 28,713   [1a]
  Fix ledger, then re-run               Rs 523,297   [1b+2b, same invoices]
  Needs the full Day Book               Rs 822,537   [2c]
```

**What I would have shipped without this:** a tool that tells a tax advocate
his client has ₹2,013,176 of unclaimed credit, when the defensible figure is
₹667,342 and the rest is a wrong input file and a ledger mistake. He would have
checked the first ten rows by hand, found bank charges, and never opened it
again.

The lesson repeats #1 and #2: the arithmetic was right every time. Only real
data showed the arithmetic was answering the wrong question.
