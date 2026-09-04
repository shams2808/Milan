# Deploying Milan to Vercel

Python serverless function, no external dependencies — `requirements.txt` is
empty on purpose.

---

## Deploy

**Via GitHub:** push, then import the repo at
[vercel.com/new](https://vercel.com/new). Framework Preset **Other**, Root
Directory `./`, Deploy.

**Via CLI:** `npm i -g vercel && vercel`

Nothing to configure. No environment variables, no password, no database.

---

## How it stays safe without a login

Milan keeps **nothing** between requests. A reconciliation is parsed, reported
on, and erased inside a single request:

- the response carries the workbook, the CSV and every Co-Pilot answer inside
  itself, so the page keeps working after the instance that made it is gone
- the uploaded files and everything derived from them are deleted **before**
  the reply is sent
- there is no session table, no `/download/{token}` route, and nothing on disk
  for a later visitor's request to land on

So there is no stored client data to protect, which is why there is no login.
The one thing an open URL does cost is compute: anyone with the link can spend
your Vercel invocations. On the Hobby tier that is a quota rather than a bill.

If you ever want to close it, Vercel offers password protection per project
under **Settings → Deployment Protection** — no code change needed.

## Limits worth knowing

| Limit | Value | Why |
|---|---|---|
| Upload size | **4 MB** total | Vercel rejects request bodies over 4.5 MB at the edge, before this code runs. Milan refuses just under it so you get a readable message instead of a platform error. |
| Page weight | ~230 KB typical | The workbook and CSV ride inside the HTML. Comfortable at a few thousand invoices; a client an order of magnitude larger would want object storage instead. |
| Execution time | 10 s (Hobby) | A 4,500-invoice reconciliation runs in about 2 s. |

## Running it locally instead

```bash
python -m milan.web
```

Serves on `http://127.0.0.1:8000`, bound to localhost. Client files never leave
the machine — for a practice handling other people's books that is a legitimate
choice, not a lesser one.

## A note on wording

The landing page used to say *"runs locally on your machine · no cloud upload"*.
That is true of the local command above and **false** of a hosted deployment,
where files are uploaded to a server before being erased. The page now says what
is true in both cases: nothing is stored, and files are erased with the response.
