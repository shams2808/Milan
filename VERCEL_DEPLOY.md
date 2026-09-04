# Deploying Milan to Vercel

Milan runs on Vercel as a Python serverless function. Zero external
dependencies — `requirements.txt` is empty on purpose.

---

## 1. Password — optional, and here is what it does and does not buy

Milan keeps **nothing** between requests. One upload is parsed, reported on,
and erased inside a single request: the response carries the workbook, the CSV
and every Co-Pilot answer inside itself, and the uploaded files and everything
derived from them are deleted before the reply is sent. There is no session
table and no `/download/{token}` route to leak one.

So a password is **not** protecting stored client data — there is none.

What it still buys:

- **Compute control.** A public URL means anyone can spend your Vercel
  invocations. On the Hobby tier that is a quota, not a bill, but it is yours.
- **Not being an open GST tool on the internet** under your parents' practice.

Leave it off and the honest risk is a stranger reconciling their own files at
your expense. Turn it on by adding, in **Vercel → Settings → Environment
Variables**:

| Name | Value |
|---|---|
| `MILAN_PASSWORD` | a password you choose |

The browser then asks once per session (any username; only the password is
checked). Unset means no gate, which is also correct for local use.

## 2. Deploy

**Via GitHub:** push, then import the repo at [vercel.com/new](https://vercel.com/new).
Framework Preset **Other**, Root Directory `./`, Deploy.

**Via CLI:** `npm i -g vercel && vercel`

---

## What the deployment actually does

Serverless instances are cold, short-lived and don't share memory, so **nothing
is stored between requests**. One upload does the whole job, and the page it
returns carries everything it will still need:

- the six-sheet workbook and the findings CSV, embedded and downloaded from the
  browser's own memory
- every Co-Pilot answer, precomputed by the same `ask_copilot()` the CLI uses,
  answered instantly with no round trip

The practical consequence is two-fold: a download still works after the
instance that produced it is gone, and **no client's books are left sitting in
a warm instance** waiting for whoever it serves next.

An earlier build kept results in a module-level dict and `/tmp`. That fails
intermittently on Vercel — the reconciliation displays, then "Session expired"
on download, depending on which instance answers — and it retained one
client's data for up to two hours where the next visitor's request would land.

## Limits worth knowing

| Limit | Value | Why |
|---|---|---|
| Upload size | **4 MB** total | Vercel rejects request bodies over 4.5 MB at the edge, before this code runs. Milan refuses just under it so you get a readable message instead of a platform error. |
| Page weight | ~230 KB typical | The workbook and CSV ride inside the HTML. Fine at a few thousand invoices; a client 10× larger would want object storage instead. |
| Execution time | 10 s (Hobby) | A 4,500-invoice reconciliation runs in about 2 s. |

## Running locally instead

```bash
python -m milan.web
```

Serves on `http://127.0.0.1:8000`, bound to localhost only. No password needed,
and client data never leaves the machine — which for a practice handling other
people's books is a legitimate choice, not a lesser one.
