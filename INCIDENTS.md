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
