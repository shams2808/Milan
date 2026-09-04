# Prompt for Claude Design — मिलान pitch deck

Attach `brand/logo.svg` alongside this prompt, then copy everything below the
line into Claude Design.

---

Build an **11-slide pitch deck** for मिलान, a GST reconciliation tool. Razorpay
AI Buildathon 2026, Track 04 (AI Finance Controller).

I will narrate over these slides myself while also demonstrating the live
website, so the deck needs to **stand on its own visually** and stay readable
when someone flips through it without me. Do not write speaker notes or
timings — just make each slide land.

## Format

- **16:9, 1920×1080**, safe margins, high contrast
- **Every slide needs a strong central graphic** — a diagram, a comparison, a
  data visualisation, or a large number. No slide should be text-only.
- Headline plus at most one supporting line. I am speaking over these; the
  graphic does the work.
- Slide 7 is the natural point where I switch to showing the live website, so
  make it a clean summary of the flow rather than a dense slide.

## Logo

**Use the attached logo exactly as supplied. Do not redraw, restyle or
regenerate it.** It is two overlapping rounded squares with the intersection
filled — two records, and the overlap is what reconciled. Place it small in a
consistent corner on every slide, large on the title and closing slides. You
may echo the overlapping-squares idea as a faint background motif, but the mark
itself stays untouched.

## Visual direction

- **Name:** मिलान (Devanagari), with "Milan" as a latin subtitle. It is the
  Hindi word Indian accountants already use for reconciliation.
- **Colour:** deep emerald `#047857` primary, darker `#064e3b`, near-black
  `#0F172A` text, off-white `#F8FAFC` grounds. Crimson `#991B1B` appears **only**
  on the two slides marked below — it should read as an alarm, so do not use it
  decoratively anywhere else.
- **Tone:** a precise professional instrument — the kind of mark a chartered
  accountant's firm puts on a letterhead. Sober, exact, confident. Not a
  consumer app, not an AI startup. No gradients, no glow, no 3D, no stock
  photography, no robots, no circuit-board or neural-network motifs.
- **Indian number formatting** — ₹37,85,669 with lakh/crore grouping, never
  ₹3,785,669.
- Monospace for anything that is an invoice number or a GSTIN.

## HARD RULE

**Do not invent, round or embellish any number, name or quote.** Use only what
is written below, exactly as written. These are real figures from a real
client's tax position and several are legally consequential. If a slide looks
sparse, make the graphic larger — never add a statistic.

---

# Slides

### 1 — Title

**Graphic:** logo large and centred on off-white, overlapping-squares motif as a
faint oversized watermark behind it.

मिलान · Milan
**Annual GST input-tax-credit reconciliation**
Razorpay AI Buildathon 2026 · Track 04

---

### 2 — Whose problem this is

**Graphic:** a dense month grid where most days are marked — audit season as a
workload. Restrained and typographic, not illustrative.

# My parents are tax consultants.
This is the job that eats their audit season.

---

### 3 — The problem, in their words

**Graphic:** a large pull-quote card, and beside it a two-pile diagram — two
stacks of documents with arrows pointing in opposite directions, labelled
*claimed but never available* and *available but never claimed*.

> "Usually a client puts all the ITC in his accounting software without knowing
> whether it appears in GSTR-2B or not. On annual reconciliation it is very
> difficult for us to find those invoices which appear in Tally but not in
> GSTR-2A, and some invoices appear in GSTR-2A without the client knowing."

— a practising tax advocate

**Two piles. Opposite directions. Both of them money.**

---

### 4 — Why a VLOOKUP cannot do it  *(hero slide)*

**Graphic:** the strongest visual in the deck. Three side-by-side comparison
rows in monospace, with only the differing characters highlighted in crimson —
a "spot the difference" that makes the viewer's eye do exactly the work an
accountant's eye does all day. Give this slide room; it should feel like the
moment the problem becomes obvious.

```
GSTR-2A              Tally
UPNUP0068      ↔     UP0068          supplier's branch prefix
4030           ↔     4029            one digit mistyped
07AABCT…       ↔     27AABCT…        same supplier, two state GSTINs
```

**The same invoice. Written two different ways.**
Excel marks every one of these as missing.

---

### 5 — The rule that shaped the build

**Graphic:** five words set enormous, dominating the slide. Beneath it a small
diagram: many suppliers as vertical columns, with matching happening only
*inside* a column and never across.

> # "GST number should be same."

— my father, describing the matching rule in five words

GSTIN became an exact blocking key. Everything hard happens inside one supplier.

---

### 6 — What it actually does

**Graphic:** three labelled columns converging into a single point, arrows
merging. Label the convergence *Table 8, GSTR-9*.

**GSTR-2A** — what the portal says was supplied
**Tally** — what the client booked
**GSTR-3B** — what was actually claimed on the return

Most tools compare the first two. The third tells you whether the credit was
ever taken.

---

### 7 — How it works  *(I switch to the live site around here)*

**Graphic:** a clean five-step horizontal flow, generously spaced:

**Two files in** → **GSTIN-blocked matching** → **split by cause** →
**6-sheet workbook** → **nothing stored**

Full financial year, about two seconds.

---

### 8 — Real client, real money

**Graphic:** a bold stat panel. The credit-note row is the largest element and
the only one in crimson.

**One real client. One financial year.**
*(anonymised: a Delhi IT distributor, FY 2025-26)*

| | |
|---|---|
| Reconciled | **2,563 portal · 1,913 books · 1,905 matched** |
| ITC confirmed | **₹5,59,73,230** |
| Available, booked, never claimed | **₹19,96,865** |
| In the portal, never booked | **₹6,43,035** · 81 bills |
| **Credit notes never recorded** | **₹37,85,669** · 145 notes |

A credit note means the supplier reduced the supply. Not recording it means
still claiming credit that was withdrawn.

---

### 9 — What broke  *(crimson slide)*

**Graphic:** the impossible number rendered huge and treated like an error
state — crimson on near-black, deliberately jarring against the calm of every
other slide.

# ₹-31,41,840
of "unclaimed tax credit"

A negative amount of money you failed to claim cannot exist.

Credit notes carry negative tax, and I was adding them to invoices — cancelling
a real **+₹6.4L** opportunity against a real **−₹37.9L** exposure. Then all 35
tests passed, because my test data contained no credit notes.

**A green test suite only proves your test data contains the failure mode.**
Ten write-ups like this are in the repo.

---

### 10 — Where the AI is, and where it is not

**Graphic:** a split panel — one side deterministic and structural, the other
the LLM, visibly smaller and boxed in by a guardrail. The quote dominates the
lower half.

**Deterministic** — matching, classification, every rupee
**LLM** — only the prose in supplier letters, and it may not invent a figure

> ## "our experience tells us more than your AI model"

— the practitioner, when I asked whether a model should judge a match

A wrong match moves a real tax claim and draws interest under section 50.

---

### 11 — Close

**Graphic:** logo large, live URL prominent, GitHub link beneath.

# Live. My parents can use it today.

Zero dependencies · 35 tests · 6-sheet audit workbook
