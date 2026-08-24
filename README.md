# Milan

**मिलान — the word a tax practitioner already uses for reconciliation.**

Annual GST input-tax-credit reconciliation. Feed it a client's GSTR-2A and
their Tally purchase register for a full financial year; it tells you what
matched, what didn't, and what each difference is going to cost.

Razorpay AI Buildathon 2026 · Track 04, AI Finance Controller

---

## Run it

No dependencies. Standard library only.

```bash
python -m milan.run --n 1200
```

```bash
python -m milan.test_milan
```

---

## The problem

This is not my idea. I described a different project to a practising tax
advocate and he told me it was easy and not worth building. This is the one he
and his colleague said actually hurts, in their words:

> *"Usually a client puts all the ITC in his accounting software without
> knowing whether it appears in GSTR-2B or not. On annual reconciliation it is
> very difficult for us to find those invoices which appear in Tally but not in
> GSTR-2A, and some invoices appear in GSTR-2A without the client knowing. It
> is very difficult to find those invoices on a yearly basis."*

Two piles, opposite directions, both money:

| Pile | Meaning | Consequence |
|---|---|---|
| **In Tally, not in 2A** | ITC claimed that was never available | Reverse it, plus interest under s.50 |
| **In 2A, not in Tally** | ITC available the client never knew about | **Lapses 30 November** under s.16(4) |

The second pile is the one nobody finds, because you cannot miss what you never
recorded. This is exactly the reconciliation behind **Table 8 of GSTR-9**.

Published guidance puts the manual cost at 2–3 hours for a client with 200–300
invoices, and 60–90 hours a month for a firm handling thirty clients.

## Why it is hard

The same invoice is written differently on each side, and the two sides are
produced by different people:

```
GSTR-2A:  INV/2025-26/0001      Tally:  INV-25-26-1
GSTR-2A:  SEL/0012              Tally:  12
GSTR-2A:  GST00006              Tally:  6
GSTR-2A:  0021                  Tally:  0012        <- transposed while typing
GSTR-2A:  BILL-003              Tally:  (blank)     <- bulk journal entry
```

A VLOOKUP on invoice number finds none of these. Annual scope makes it worse:
a supplier who files late puts the invoice in a different month's 2A than the
books, so period-by-period matching reports a difference that isn't one.

## The rule that shapes the whole thing

From the practitioner: **"GST number should be same."** GSTIN is an exact
blocking key — the matcher never compares invoices across suppliers, no matter
how well the numbers line up. Everything difficult happens *inside* one
supplier.

The one place that rule costs something is a GSTIN mistyped in Tally, which
puts the same invoice in **both** piles at once. Milan does not auto-correct
this — it reports it as a books correction with the two GSTINs side by side,
and asks you to fix Tally and re-run.

---

## Result

1,200-invoice synthetic financial year:

```
matched                 :  1041 invoices   Rs 23,026,783 ITC confirmed
    exact                601
    format_variant       302
    supplier_code         51
    amount_mismatch       40
    typo_in_number        27
    value_and_date        20
    needs review           0

PILE 1  in Tally, not in 2A -- ITC claimed that was never available
  113 invoices   Rs 2,414,743 at risk of reversal + interest u/s 50

PILE 2  in 2A, not in Tally -- ITC available that was never claimed
  86 invoices   Rs 2,406,295 claimable
  deadline 30 Nov 2026 (s.16(4)) -- 98 days left, then it lapses

SUSPECTED GSTIN TYPO IN BOOKS   17 invoices
DUPLICATE IN BOOKS              23 extra rows double-counted

precision 100.000%   recall 100.000%   wrong matches 0
```

**Read that 100% with suspicion.** It means the cascade handles every
distortion I thought to inject, generator and matcher written by the same
person. It says nothing about the ones I didn't think of. An earlier run
scored 99.9% while two serious bugs sat in the normaliser —
[`INCIDENTS.md`](INCIDENTS.md) is the log of finding them, and every bug in it
was caught by making the test data harder, never by reading the code.

Real 2A and Tally files arrive from the practitioner on **1 September**, after
his 31 August filing deadline. That is the first honest test this will get.

---

## How it matches

Deterministic cascade, strongest first, one-to-one, within a single GSTIN. A
weaker stage can never overturn a stronger one, and ambiguity is never resolved
by guessing — several equally good candidates means the row goes to review with
its candidates attached.

| Stage | Fires when |
|---|---|
| `exact` | same number after punctuation and leading zeros, same tax |
| `format_variant` | same number once FY and document-type noise is stripped |
| `amount_mismatch` | same number and date, **tax differs** — a finding, not a failure |
| `supplier_code` | one side carries the supplier's own prefix (`SEL/0012` vs `12`) |
| `typo_in_number` | one character out, tax **and** date agree |
| `value_and_date` | number genuinely missing on one side; unique candidate |

Every near-miss stage requires tax *and* date to agree, so a near-miss number can
never carry a match on its own.

## Where AI is used, and where it deliberately is not

| Job | Tool | Why |
|---|---|---|
| GSTIN blocking | exact match | The practitioner's hard rule, not my heuristic |
| Invoice normalisation | token cascade | Deterministic and testable |
| Near-miss matching | Damerau-Levenshtein | A wrong match moves a real ITC claim |
| **Ambiguous residual** | **LLM, confidence-gated** | Gets the row plus its candidates; picks one or abstains |
| **Supplier chase messages** | **LLM** | Genuine language task, per-supplier context |
| **Plain-English exception reasons** | **LLM** | Turns a row into something a client will act on |
| **Asserting two invoices are the same** | **never an LLM** | |

The LLM is only ever offered candidates the deterministic cascade already
proposed. It cannot invent a match.

---

## Status

| | |
|---|---|
| Normalisation, matching cascade, two-pile report, GSTIN-typo detection | done |
| Synthetic year with ground truth + measured precision/recall | done |
| 13 regression tests, one per bug found | done |
| Real 2A / Tally file loaders (JSON, Excel, CSV) | 1 Sept, with real files |
| LLM tail on the review queue | pending |
| Supplier chase messages | pending |
| Practitioner validation session | 1–2 Sept |

## Open questions for the practitioner

1. Tax tolerance — is ₹1 right, or should it be ₹10?
2. When you eyeball `INV/25-26/1` against `1`, is same-supplier plus
   same-amount enough for you to call it a match?
3. Which existing tool do you use for this today, and what does it get wrong?
