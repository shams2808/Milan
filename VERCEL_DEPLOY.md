# Deploying Milan to Vercel

Milan runs on Vercel as a Python serverless function. Zero external
dependencies — `requirements.txt` is empty on purpose.

---

## 1. Set the password FIRST

Milan handles a real client's GSTINs, supplier list and complete tax position.
A Vercel URL is public: without a password, anyone who has the link can upload,
reconcile and download.

In **Vercel → Project → Settings → Environment Variables**, add:

| Name | Value |
|---|---|
| `MILAN_PASSWORD` | a password you choose |

Apply it to **Production, Preview and Development**.

The browser then asks for it once per session (username is ignored, any value
works). Leaving the variable unset disables the gate entirely — correct for
running locally on `127.0.0.1`, wrong for anything with a public URL.

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

The practical consequence: a download still works after the instance that
produced it is gone. An earlier build kept results in a module-level dict and
`/tmp`, which works on a laptop and fails intermittently on Vercel — the
reconciliation would display and then "Session expired" on download, depending
on which instance answered.

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
