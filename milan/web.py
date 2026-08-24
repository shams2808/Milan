"""Upload two files, get the workbook back.

    python -m milan.web        then open http://127.0.0.1:8000

Binds to 127.0.0.1 only, deliberately. This handles a real client's financial
records; it is a tool that runs on the practitioner's own machine, not a
service. Uploads are held in a temp directory and deleted when the process
exits, and nothing is written into the repository.

Standard library only, like the rest of Milan -- http.server plus a small
multipart parser. `cgi.FieldStorage` would have done the parsing but it is
deprecated in 3.11 and removed in 3.13, so the form data is parsed here.
"""

from __future__ import annotations

import html
import shutil
import tempfile
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import rupees
from .export import write_csv
from .loaders import load_gstr2a, load_tally
from .match import reconcile
from .report import ITC_DEADLINE, classify_ineligible, classify_unclaimed
from .workbook import partial_mismatches, write_workbook

MAX_UPLOAD = 64 * 1024 * 1024
_RESULTS: dict[str, Path] = {}
_TMP = Path(tempfile.mkdtemp(prefix="milan-"))

_CSS = """
*{box-sizing:border-box} body{font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#f4f6f8;color:#1b2733}
.wrap{max-width:860px;margin:0 auto;padding:40px 24px}
h1{margin:0 0 4px;font-size:26px} .sub{color:#5b6b7c;margin:0 0 28px}
.card{background:#fff;border:1px solid #dde3e9;border-radius:10px;padding:26px;margin-bottom:20px}
label{display:block;font-weight:600;margin:0 0 6px}
.hint{color:#5b6b7c;font-size:14px;margin:0 0 10px}
input[type=file]{width:100%;padding:12px;border:1px dashed #b9c4cf;border-radius:8px;background:#fafbfc}
.field{margin-bottom:22px}
button{background:#0b6b3a;color:#fff;border:0;border-radius:8px;padding:13px 26px;
font-size:16px;font-weight:600;cursor:pointer}
button:hover{background:#095c31}
table{border-collapse:collapse;width:100%;margin-top:6px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e6ebf0;font-size:15px}
th{background:#f0f3f6;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#5b6b7c}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.big{font-size:30px;font-weight:700;color:#0b6b3a;margin:2px 0}
.dl{display:inline-block;background:#0b6b3a;color:#fff;text-decoration:none;
padding:12px 22px;border-radius:8px;font-weight:600;margin:6px 10px 0 0}
.dl.alt{background:#41505f}
.err{background:#fdf2f2;border:1px solid #e6b8b8;color:#8a1f1f;padding:16px;border-radius:8px}
a.back{color:#0b6b3a}
code{background:#eef2f5;padding:2px 6px;border-radius:4px;font-size:14px}
"""

_FORM = """<!doctype html><meta charset="utf-8"><title>Milan - GST ITC Reconciliation</title>
<style>{css}</style><div class=wrap>
<h1>Milan</h1>
<p class=sub>Annual GST input tax credit reconciliation &mdash; GSTR-2A against the Tally purchase register.</p>
<div class=card><form method=post action=/reconcile enctype=multipart/form-data>
  <div class=field>
    <label>GSTR-2A annual summary</label>
    <p class=hint>The Excel file downloaded from the GST portal.</p>
    <input type=file name=gstr2a accept=".xlsx" required>
  </div>
  <div class=field>
    <label>Tally purchase register</label>
    <p class=hint>Export from Tally. You can select more than one file &mdash;
       add the journal or payment register too if you have them.</p>
    <input type=file name=tally accept=".xlsx" multiple required>
  </div>
  <button type=submit>Reconcile</button>
</form></div></div>"""

_RESULT = """<!doctype html><meta charset="utf-8"><title>Milan - Result</title>
<style>{css}</style><div class=wrap>
<h1>Reconciliation complete</h1>
<p class=sub>{gstr_rows} bills in GSTR-2A &middot; {tally_rows} bills in Tally &middot; {matched} matched</p>
<div class=card>
  <p style="margin:0;color:#5b6b7c">Input tax credit available but never claimed</p>
  <p class=big>{claim}</p>
  <p style="margin:0;color:#5b6b7c">Across {claim_n} bills. Expires 30 November 2026 &mdash;
     <strong>{days} days left</strong>.</p>
</div>
<div class=card>
<table><tr><th>Category</th><th class=n>Bills</th><th class=n>Value</th><th>What to do</th></tr>
{rows}
</table>
</div>
<div class=card>
  <a class=dl href="/download/{token}/xlsx">Download Excel workbook</a>
  <a class="dl alt" href="/download/{token}/csv">Download CSV</a>
  <p class=hint style="margin-top:16px">Five sheets: Summary, Not in Tally, Not in 2A,
     Partial Mismatch (both bills side by side), Other Ledgers.</p>
</div>
<p><a class=back href="/">Reconcile another client</a></p></div>"""

_ERROR = """<!doctype html><meta charset="utf-8"><title>Milan - Error</title>
<style>{css}</style><div class=wrap><h1>Could not read those files</h1>
<div class=card><div class=err>{msg}</div>
<p class=hint style="margin-top:16px">Milan expects the GSTR-2A annual summary from the
portal (it looks for a sheet named like <code>B2B - Only Invoice wise</code>) and a Tally
register export with <code>Particulars</code>, <code>GSTIN/UIN</code> and
<code>Gross Total</code> columns.</p></div>
<p><a class=back href="/">Try again</a></p></div>"""


def _parse_multipart(body: bytes, boundary: bytes) -> list[tuple[str, str, bytes]]:
    """Return [(field_name, filename, content)]. Minimal but strict enough:
    it only accepts parts that actually carry a filename."""
    out = []
    for chunk in body.split(b"--" + boundary):
        if not chunk.strip() or chunk.strip() == b"--":
            continue
        head, _, data = chunk.partition(b"\r\n\r\n")
        if not _:
            continue
        disp = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-disposition"):
                disp = line.decode("utf-8", "replace")
        if "filename=" not in disp:
            continue
        name = disp.split('name="', 1)[1].split('"', 1)[0]
        fname = disp.split('filename="', 1)[1].split('"', 1)[0]
        if fname:
            out.append((name, fname, data.rstrip(b"\r\n")))
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "Milan"

    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/":
            return self._send(_FORM.format(css=_CSS))
        if self.path.startswith("/download/"):
            try:
                _, _, token, kind = self.path.split("/", 3)
            except ValueError:
                return self._send(_ERROR.format(css=_CSS, msg="Bad download link."), 400)
            folder = _RESULTS.get(token)
            if folder is None:
                return self._send(_ERROR.format(css=_CSS, msg="That result has expired."), 404)
            path = folder / ("reconciliation.xlsx" if kind == "xlsx" else "findings.csv")
            if not path.exists():
                return self._send(_ERROR.format(css=_CSS, msg="File not found."), 404)
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(_ERROR.format(css=_CSS, msg="Page not found."), 404)

    def do_POST(self) -> None:
        if self.path != "/reconcile":
            return self._send(_ERROR.format(css=_CSS, msg="Page not found."), 404)

        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            return self._send(_ERROR.format(css=_CSS, msg="Malformed upload."), 400)
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return self._send(_ERROR.format(css=_CSS, msg="Files are too large."), 413)

        boundary = ctype.split("boundary=", 1)[1].strip('"').encode()
        parts = _parse_multipart(self.rfile.read(length), boundary)

        token = uuid.uuid4().hex
        folder = _TMP / token
        folder.mkdir(parents=True, exist_ok=True)

        gstr_path, tally_paths = None, []
        for field, fname, data in parts:
            safe = Path(fname).name  # never trust a client-supplied path
            dest = folder / f"{field}_{len(tally_paths)}_{safe}"
            dest.write_bytes(data)
            if field == "gstr2a":
                gstr_path = dest
            elif field == "tally":
                tally_paths.append(dest)

        if gstr_path is None or not tally_paths:
            return self._send(_ERROR.format(css=_CSS, msg="Please choose both files."), 400)

        try:
            gstr = load_gstr2a(str(gstr_path))
            tally, _vtypes = load_tally([str(p) for p in tally_paths])
            res = reconcile(tally, gstr)
            write_workbook(str(folder / "reconciliation.xlsx"), tally, gstr, res)
            write_csv(str(folder / "findings.csv"), tally, gstr, res)
        except Exception as exc:  # surface the real reason, not a generic 500
            shutil.rmtree(folder, ignore_errors=True)
            return self._send(_ERROR.format(css=_CSS, msg=html.escape(str(exc))), 400)

        _RESULTS[token] = folder
        self._send(_result_page(token, tally, gstr, res))


def _result_page(token: str, tally, gstr, res) -> str:
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)
    claim = unclaimed.get("missing_invoice", [])
    not_in_2a = ineligible.get("not_filed", []) + ineligible.get("supplier_absent", [])
    other = unclaimed.get("supplier_absent", [])
    conflicts = unclaimed.get("other_registration", [])
    mismatches = partial_mismatches(res)

    def total(rows):
        return sum(i.tax for i in rows)

    def row(label, n, value, action):
        return (f"<tr><td>{label}</td><td class=n>{n}</td>"
                f"<td class=n>{value}</td><td>{action}</td></tr>")

    rows = "".join([
        row("Not in Tally", len(claim), rupees(total(claim)), "Claim before 30 November"),
        row("Not in 2A", len(not_in_2a), rupees(total(not_in_2a)),
            "Chase the supplier, or reverse with interest u/s 50"),
        row("Partial mismatch &ndash; amount or date", len(mismatches), "&mdash;",
            "Both bills shown side by side; confirm which is right"),
        row("Partial mismatch &ndash; GST number", len(conflicts), rupees(total(conflicts)),
            "Same supplier, two registrations; correct the ledger"),
        row("Other ledgers (FYI)", len(other), rupees(total(other)),
            "Nominal, reconciled separately"),
    ])
    return _RESULT.format(
        css=_CSS, token=token,
        gstr_rows=len(gstr), tally_rows=len(tally), matched=len(res.pairs),
        claim=rupees(total(claim)), claim_n=len(claim),
        days=(ITC_DEADLINE - date.today()).days, rows=rows,
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\n  Milan is running at http://127.0.0.1:{args.port}")
    print(f"  Uploads go to {_TMP} and are deleted when you stop the server.")
    print("  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopping, cleaning up uploads")
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
