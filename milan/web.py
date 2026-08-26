"""Upload two or three files, get the interactive three-way reconciliation and workbook back.

    python -m milan.web        then open http://127.0.0.1:8000

Binds to 127.0.0.1 only, deliberately. This handles a real client's financial
records; it is a tool that runs on the practitioner's own machine, not a
cloud service. Uploads are held in a temporary directory and purged when the
process terminates. Zero external dependencies (standard library only).
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
from .loaders import load_gstr2a, load_gstr3b, load_tally
from .match import reconcile
from .report import (
    ITC_DEADLINE,
    classify_ineligible,
    classify_unclaimed,
    compute_three_way_position,
)
from .workbook import partial_mismatches, write_workbook

MAX_UPLOAD = 64 * 1024 * 1024
_RESULTS: dict[str, Path] = {}
_TMP = Path(tempfile.mkdtemp(prefix="milan-"))

_CSS = """
:root {
  --primary: #047857;
  --primary-dark: #064e3b;
  --primary-light: #ecfdf5;
  --primary-border: #a7f3d0;
  --accent: #4f46e5;
  --accent-light: #eef2ff;
  --text-main: #0f172a;
  --text-muted: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --border: #e2e8f0;
  --border-focus: #10b981;
  --danger: #dc2626;
  --danger-light: #fef2f2;
  --warning: #d97706;
  --warning-light: #fffbeb;
  --radius: 12px;
  --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.07), 0 2px 4px -2px rgb(0 0 0 / 0.05);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.08), 0 4px 6px -4px rgb(0 0 0 / 0.04);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background-color: var(--bg);
  color: var(--text-main);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
}

.wrap {
  max-width: 980px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

/* Header & Brand */
.brand-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}

.brand-logo-area {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #059669, #047857);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 800;
  font-size: 24px;
  box-shadow: 0 4px 10px rgba(5, 150, 105, 0.25);
}

.brand-title {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-title span.deva {
  font-size: 19px;
  font-weight: 500;
  color: #059669;
  background: var(--primary-light);
  padding: 2px 10px;
  border-radius: 20px;
  border: 1px solid var(--primary-border);
}

.brand-sub {
  color: var(--text-muted);
  font-size: 15px;
  margin-top: 2px;
}

.badge-local {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.badge-local svg {
  width: 14px;
  height: 14px;
  fill: #059669;
}

/* Card */
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 30px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

.card-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 22px;
}

/* Upload Dropzones */
.upload-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
  margin-bottom: 26px;
}

.dropzone {
  position: relative;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 24px 20px;
  text-align: center;
  background: #fafbfc;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.dropzone:hover, .dropzone.dragover {
  border-color: #059669;
  background: #f0fdf4;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(5, 150, 105, 0.08);
}

.dropzone.optional {
  border-color: #cbd5e1;
  background: #fbfbfe;
}
.dropzone.optional:hover {
  border-color: #6366f1;
  background: #f5f7ff;
}

.dropzone input[type="file"] {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.dz-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  color: #475569;
  transition: all 0.2s ease;
}

.dropzone:hover .dz-icon {
  background: #d1fae5;
  color: #059669;
}

.dropzone.optional:hover .dz-icon {
  background: #e0e7ff;
  color: #4f46e5;
}

.dz-title {
  font-weight: 700;
  font-size: 15px;
  color: #1e293b;
  margin-bottom: 4px;
}

.dz-pill {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 12px;
  margin-bottom: 8px;
}
.dz-pill.req { background: #e0f2fe; color: #0284c7; }
.dz-pill.opt { background: #ede9fe; color: #7c3aed; }

.dz-sub {
  font-size: 13px;
  color: #64748b;
  line-height: 1.4;
}

.dz-file-name {
  margin-top: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #047857;
  background: #d1fae5;
  padding: 4px 10px;
  border-radius: 6px;
  max-width: 90%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: none;
}

/* Submit CTA */
.cta-area {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
}

.cta-hints {
  font-size: 13px;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 8px;
}

button.btn-primary {
  background: linear-gradient(135deg, #059669, #047857);
  color: white;
  border: 0;
  border-radius: 10px;
  padding: 14px 34px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3);
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

button.btn-primary:hover {
  background: linear-gradient(135deg, #047857, #065f46);
  box-shadow: 0 6px 18px rgba(5, 150, 105, 0.4);
  transform: translateY(-1px);
}

button.btn-primary:active {
  transform: translateY(0);
}

/* Feature grid on home */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  margin-top: 36px;
}

.feature-box {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
}

.feature-box h4 {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.feature-box p {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

/* Result Styles */
.hero-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}

.metric-card {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  position: relative;
  overflow: hidden;
}

.metric-card.accent {
  background: #f0fdf4;
  border-color: #86efac;
}

.metric-card.alert {
  background: #fff7ed;
  border-color: #fed7aa;
}

.metric-label {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  margin-bottom: 6px;
}

.metric-val {
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.metric-card.accent .metric-val { color: #047857; }
.metric-card.alert .metric-val { color: #c2410c; }

.metric-sub {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}

/* Alert Banner */
.highlight-banner {
  background: linear-gradient(135deg, #fef2f2, #fff1f2);
  border: 1px solid #fecdd3;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.highlight-banner.success {
  background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
  border-color: #a7f3d0;
}

.hb-left {
  display: flex;
  flex-direction: column;
}

.hb-tag {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: #be123c;
  letter-spacing: 0.04em;
}

.hb-title {
  font-size: 28px;
  font-weight: 800;
  color: #9f1239;
  letter-spacing: -0.02em;
  margin: 2px 0 4px;
}

.hb-desc {
  font-size: 14px;
  color: #475569;
}

.hb-badge {
  background: #ffffff;
  padding: 10px 18px;
  border-radius: 8px;
  border: 1px solid #fecdd3;
  font-size: 13px;
  font-weight: 700;
  color: #be123c;
  text-align: right;
}

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
}

th, td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  text-align: left;
}

th {
  background: #f8fafc;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #475569;
}

td.n {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  white-space: nowrap;
}

.delta-pos { color: #047857; font-weight: 600; }
.delta-neg { color: #b91c1c; font-weight: 600; }

.status-pill {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
  background: #f1f5f9;
  color: #334155;
}
.status-pill.claim { background: #dcfce7; color: #15803d; }
.status-pill.reverse { background: #fee2e2; color: #b91c1c; }
.status-pill.review { background: #fef3c7; color: #b45309; }

/* Callout Info Box */
.info-callout {
  background: #f8fafc;
  border-left: 4px solid #059669;
  padding: 16px 20px;
  border-radius: 0 8px 8px 0;
  margin: 18px 0;
  font-size: 14px;
  color: #334155;
  line-height: 1.5;
}

.info-callout strong {
  color: #0f172a;
}

/* Actions */
.action-card {
  background: linear-gradient(135deg, #064e3b, #047857);
  color: white;
  border-radius: var(--radius);
  padding: 26px 30px;
  margin-top: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--shadow-lg);
}

.action-text h3 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 4px;
}
.action-text p {
  font-size: 14px;
  color: #a7f3d0;
}

.btn-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-download {
  background: #ffffff;
  color: #064e3b;
  text-decoration: none;
  font-weight: 700;
  font-size: 15px;
  padding: 12px 24px;
  border-radius: 8px;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}

.btn-download:hover {
  background: #f0fdf4;
  transform: translateY(-1px);
}

.btn-download.alt {
  background: rgba(255, 255, 255, 0.15);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.btn-download.alt:hover {
  background: rgba(255, 255, 255, 0.25);
}

.nav-back {
  margin-top: 24px;
  text-align: center;
}
.nav-back a {
  color: #059669;
  text-decoration: none;
  font-weight: 600;
  font-size: 14px;
}
.nav-back a:hover {
  text-decoration: underline;
}

/* Spinner Overlay */
#loader {
  display: none;
  position: fixed;
  top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 9999;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
}

.spinner {
  width: 50px;
  height: 50px;
  border: 4px solid rgba(255, 255, 255, 0.2);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 18px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .hero-metric-grid { grid-template-columns: repeat(2, 1fr); }
  .feature-grid { grid-template-columns: 1fr; }
  .action-card { flex-direction: column; text-align: center; gap: 18px; }
}
"""

_FORM_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Milan — Annual GST ITC Reconciliation</title>
  <style>/*INJECT_CSS*/</style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <h3 style="font-weight:700;font-size:20px;">Reconciling GST Books...</h3>
    <p style="color:#cbd5e1;font-size:14px;margin-top:4px;">Running deterministic cascade within supplier GSTINs</p>
  </div>

  <div class="wrap">
    <!-- Header -->
    <header class="brand-header">
      <div class="brand-logo-area">
        <div class="brand-icon">M</div>
        <div>
          <div class="brand-title">
            Milan <span class="deva">मिलान</span>
          </div>
          <div class="brand-sub">Annual GST Input Tax Credit Reconciliation · Track 04 AI Finance Controller</div>
        </div>
      </div>
      <div class="badge-local">
        <svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>
        100% Local Execution
      </div>
    </header>

    <!-- Upload Card -->
    <div class="card">
      <div class="card-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
        Upload Client Records
      </div>
      <div class="card-desc">
        Select the client's GST portal return exports and Tally purchase register for a full financial year.
      </div>

      <form id="recon-form" method="post" action="/reconcile" enctype="multipart/form-data">
        <div class="upload-grid">
          
          <!-- GSTR-2A Zone -->
          <div class="dropzone" id="dz-2a">
            <div class="dz-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
            </div>
            <span class="dz-pill req">Required</span>
            <div class="dz-title">GSTR-2A Annual Summary</div>
            <div class="dz-sub">Portal inward supply export (reads <code>B2B - Only Invoice</code>)</div>
            <input type="file" name="gstr2a" id="file-2a" accept=".xlsx" required onchange="handleFileSelected(this, 'dz-2a')">
            <div class="dz-file-name" id="name-dz-2a"></div>
          </div>

          <!-- Tally Zone -->
          <div class="dropzone" id="dz-tally">
            <div class="dz-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
            </div>
            <span class="dz-pill req">Required</span>
            <div class="dz-title">Tally Purchase Register</div>
            <div class="dz-sub">Day Book or Purchase export (multi-select supported)</div>
            <input type="file" name="tally" id="file-tally" accept=".xlsx" multiple required onchange="handleFileSelected(this, 'dz-tally')">
            <div class="dz-file-name" id="name-dz-tally"></div>
          </div>

          <!-- GSTR-3B Zone (Phase 1-4 Feature) -->
          <div class="dropzone optional" id="dz-3b">
            <div class="dz-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
            </div>
            <span class="dz-pill opt">Optional · Unlocks 3-Way</span>
            <div class="dz-title">GSTR-3B Monthly Summary</div>
            <div class="dz-sub">12-month summary for Table 8 & timing differences</div>
            <input type="file" name="gstr3b" id="file-3b" accept=".xlsx" onchange="handleFileSelected(this, 'dz-3b')">
            <div class="dz-file-name" id="name-dz-3b"></div>
          </div>

        </div>

        <div class="cta-area">
          <div class="cta-hints">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
            No data leaves this machine. Standard library only.
          </div>
          <button type="submit" class="btn-primary" onclick="showLoader()">
            Run Reconciliation
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
          </button>
        </div>
      </form>
    </div>

    <!-- Feature Pillars -->
    <div class="feature-grid">
      <div class="feature-box">
        <h4>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
          Section 16(4) Lapse Alert
        </h4>
        <p>Uncovers portal invoices that were never booked in accounting software before the statutory November 30 deadline.</p>
      </div>
      <div class="feature-box">
        <h4>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          Section 50 Interest Guard
        </h4>
        <p>Isolates credit claimed in Tally that was never filed by suppliers, preventing steep reversal penalties.</p>
      </div>
      <div class="feature-box">
        <h4>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line></svg>
          Table 8 Position
        </h4>
        <p>Reconciles Available vs Booked vs Claimed and exports an exhaustive 6-sheet review workbook.</p>
      </div>
    </div>
  </div>

  <script>
    function handleFileSelected(input, dzId) {
      const nameEl = document.getElementById('name-' + dzId);
      if (input.files && input.files.length > 0) {
        if (input.files.length === 1) {
          nameEl.textContent = '✓ ' + input.files[0].name;
        } else {
          nameEl.textContent = '✓ ' + input.files.length + ' files selected';
        }
        nameEl.style.display = 'inline-block';
      } else {
        nameEl.style.display = 'none';
      }
    }

    function showLoader() {
      const f2a = document.getElementById('file-2a');
      const ftally = document.getElementById('file-tally');
      if (f2a.files.length && ftally.files.length) {
        document.getElementById('loader').style.display = 'flex';
      }
    }
  </script>
</body>
</html>"""

_RESULT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Milan — Reconciliation Result</title>
  <style>/*INJECT_CSS*/</style>
</head>
<body>
  <div class="wrap">
    <!-- Header -->
    <header class="brand-header">
      <div class="brand-logo-area">
        <div class="brand-icon">✓</div>
        <div>
          <div class="brand-title">Reconciliation Complete</div>
          <div class="brand-sub">__GSTR_ROWS__ portal bills &middot; __TALLY_ROWS__ books bills &middot; __MATCHED__ confirmed matches</div>
        </div>
      </div>
      <div class="badge-local">
        Table 8 Diagnostic
      </div>
    </header>

    <!-- Top Metric Grid -->
    <div class="hero-metric-grid">
      <div class="metric-card">
        <div class="metric-label">2A Available</div>
        <div class="metric-val">__TOTAL_2A__</div>
        <div class="metric-sub">__GSTR_ROWS__ Inward Bills</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Tally Booked</div>
        <div class="metric-val">__TOTAL_TALLY__</div>
        <div class="metric-sub">__TALLY_ROWS__ Inward Bills</div>
      </div>
      <div class="metric-card accent">
        <div class="metric-label">ITC Confirmed</div>
        <div class="metric-val">__MATCHED_TAX__</div>
        <div class="metric-sub">__MATCHED__ Exact Pairs</div>
      </div>
      <div class="metric-card alert">
        <div class="metric-label">Unclaimed in Books</div>
        <div class="metric-val">__CLAIM__</div>
        <div class="metric-sub">__CLAIM_N__ Bills (__DAYS__d left)</div>
      </div>
    </div>

    <!-- Highlight Hero Banner for Lapsing ITC -->
    <div class="highlight-banner">
      <div class="hb-left">
        <span class="hb-tag">Statutory Action Required u/s 16(4)</span>
        <div class="hb-title">__CLAIM__</div>
        <div class="hb-desc">Inward supplies verified on GST portal that your client never booked in accounting software.</div>
      </div>
      <div class="hb-badge">
        Lapses on 30 Nov 2026<br>
        <strong>__DAYS__ Days Left</strong>
      </div>
    </div>

    __THREE_WAY_CARD__

    <!-- Findings Breakdown Table -->
    <div class="card">
      <div class="card-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
        Reconciliation Findings by Cause
      </div>
      <div class="card-desc">Every discrepancy classified by actionable tax remedy rather than raw unassigned totals.</div>
      <table>
        <tr>
          <th>Category</th>
          <th class="n">Bills</th>
          <th class="n">ITC Value</th>
          <th>What to Do</th>
        </tr>
        __ROWS__
      </table>
    </div>

    __MONTHLY_CARD__

    <!-- Download Action Card -->
    <div class="action-card">
      <div class="action-text">
        <h3>Export Review Workbook</h3>
        <p>__SHEET_DESC__</p>
      </div>
      <div class="btn-group">
        <a class="btn-download" href="/download/__TOKEN__/xlsx">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Download Excel Workbook
        </a>
        <a class="btn-download alt" href="/download/__TOKEN__/csv">
          Download CSV
        </a>
      </div>
    </div>

    <div class="nav-back">
      <a href="/">← Reconcile another client</a>
    </div>

  </div>
</body>
</html>"""

_ERROR_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Milan — Upload Error</title>
  <style>/*INJECT_CSS*/</style>
</head>
<body>
  <div class="wrap">
    <header class="brand-header">
      <div class="brand-logo-area">
        <div class="brand-icon" style="background:#dc2626;">!</div>
        <div>
          <div class="brand-title">Could not reconcile files</div>
          <div class="brand-sub">Verification error occurred while parsing spreadsheets</div>
        </div>
      </div>
    </header>
    <div class="card">
      <div class="err">__MSG__</div>
      <p class="card-desc" style="margin-top:16px;">
        Milan expects the GSTR-2A annual summary from the GST portal (reads <code>B2B - Only Invoice wise</code>) and a Tally register export with <code>Particulars</code>, <code>GSTIN/UIN</code>, and <code>Gross Total</code>.
      </p>
    </div>
    <div class="nav-back">
      <a href="/">← Try again</a>
    </div>
  </div>
</body>
</html>"""


def _parse_multipart(body: bytes, boundary: bytes) -> list[tuple[str, str, bytes]]:
    out = []
    delim = b"--" + boundary
    for chunk in body.split(delim):
        if not chunk.strip() or chunk.strip() == b"--":
            continue
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
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

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        """A browser that navigates away mid-upload drops the socket, and the
        write that follows raises ConnectionAbortedError (WinError 10053).
        That is the client's normal behaviour, not a server fault, so it is
        swallowed here instead of dumping a traceback the practitioner reads
        as a crash."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def handle_error(self, request, client_address):
        pass

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def do_GET(self) -> None:
        if self.path == "/":
            return self._send(_FORM_HTML.replace("/*INJECT_CSS*/", _CSS))
        if self.path.startswith("/download/"):
            try:
                _, _, token, kind = self.path.split("/", 3)
            except ValueError:
                err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Bad download link.")
                return self._send(err_page, 400)
            folder = _RESULTS.get(token)
            if folder is None:
                err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "That result has expired.")
                return self._send(err_page, 404)
            path = folder / ("reconciliation.xlsx" if kind == "xlsx" else "findings.csv")
            if not path.exists():
                err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "File not found.")
                return self._send(err_page, 404)
            data = path.read_bytes()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                self.close_connection = True   # cancelled download; not an error
            return
        err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Page not found.")
        self._send(err_page, 404)

    def do_POST(self) -> None:
        if self.path != "/reconcile":
            err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Page not found.")
            return self._send(err_page, 404)

        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Malformed upload.")
            return self._send(err_page, 400)
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Files are too large.")
            return self._send(err_page, 413)

        boundary = ctype.split("boundary=", 1)[1].strip('"').encode()
        parts = _parse_multipart(self.rfile.read(length), boundary)

        token = uuid.uuid4().hex
        folder = _TMP / token
        folder.mkdir(parents=True, exist_ok=True)

        gstr_path, tally_paths, gstr3b_path = None, [], None
        for field, fname, data in parts:
            safe = Path(fname).name
            dest = folder / f"{field}_{len(tally_paths)}_{safe}"
            dest.write_bytes(data)
            if field == "gstr2a":
                gstr_path = dest
            elif field == "tally":
                tally_paths.append(dest)
            elif field == "gstr3b":
                gstr3b_path = dest

        if gstr_path is None or not tally_paths:
            shutil.rmtree(folder, ignore_errors=True)
            err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", "Please choose both required files (GSTR-2A and Tally).")
            return self._send(err_page, 400)

        try:
            gstr = load_gstr2a(str(gstr_path))
            tally, _vtypes = load_tally([str(p) for p in tally_paths])
            gstr3b = load_gstr3b(str(gstr3b_path)) if gstr3b_path else None
            res = reconcile(tally, gstr)
            write_workbook(str(folder / "reconciliation.xlsx"), tally, gstr, res, gstr3b=gstr3b)
            write_csv(str(folder / "findings.csv"), tally, gstr, res)
        except Exception as exc:
            shutil.rmtree(folder, ignore_errors=True)
            err_page = _ERROR_HTML.replace("/*INJECT_CSS*/", _CSS).replace("__MSG__", html.escape(str(exc)))
            return self._send(err_page, 400)

        _RESULTS[token] = folder
        self._send(_result_page(token, tally, gstr, res, gstr3b=gstr3b))


def _result_page(token: str, tally, gstr, res, gstr3b=None) -> str:
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)
    claim = unclaimed.get("missing_invoice", [])
    not_in_2a = ineligible.get("not_filed", []) + ineligible.get("supplier_absent", [])
    other = unclaimed.get("supplier_absent", [])
    conflicts = unclaimed.get("other_registration", [])
    mismatches = partial_mismatches(res)

    def total(rows):
        return sum(i.tax for i in rows)

    def row(label, n, value, action, pill_class):
        return (f"<tr><td><strong>{label}</strong></td><td class=n>{n}</td>"
                f"<td class=n><strong>{value}</strong></td>"
                f"<td><span class=\"status-pill {pill_class}\">{action}</span></td></tr>")

    rows = "".join([
        row("Not in Tally (Missing Inward)", len(claim), rupees(total(claim)), "Claim before 30 Nov", "claim"),
        row("Not in 2A (Unfiled by Supplier)", len(not_in_2a), rupees(total(not_in_2a)),
            "Chase supplier / Reverse u/s 50", "reverse"),
        row("Partial Mismatch (Amount/Date)", len(mismatches), "&mdash;",
            "Review paired bills side by side", "review"),
        row("GSTIN Conflict (Multi-State PAN)", len(conflicts), rupees(total(conflicts)),
            "Correct supplier ledger in Tally", "review"),
        row("Other Ledgers (Nominal Out of Scope)", len(other), rupees(total(other)),
            "Reconciled via other ledgers", "claim"),
    ])

    three_way_card = ""
    monthly_card = ""
    sheet_desc = "Five sheets: Summary, Not in Tally, Not in 2A, Partial Mismatch, and Other Ledgers."

    total_2a_val = rupees(sum(i.tax for i in gstr))
    total_tally_val = rupees(sum(i.tax for i in tally))
    matched_tax_val = rupees(sum(p.gstr.tax for p in res.pairs))

    if gstr3b is not None:
        twp = compute_three_way_position(tally, gstr, res, gstr3b)
        sheet_desc = "Six sheets: Summary, Not in Tally, Not in 2A, Partial Mismatch, Other Ledgers, and ITC Position."

        three_way_card = f"""
    <!-- Three-Way Table 8 Card -->
    <div class="card">
      <div class="card-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
        Three-Way ITC Position (Table 8 Shape)
      </div>
      <div class="card-desc">Comprehensive reconciliation between GSTR-2A (Available), Tally (Booked), and GSTR-3B (Claimed).</div>

      <div class="hero-metric-grid" style="margin-bottom:18px;">
        <div class="metric-card">
          <div class="metric-label">2A Available (Table 8A)</div>
          <div class="metric-val">{rupees(twp.available_2a)}</div>
          <div class="metric-sub">Portal Inward Tax</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Tally Inward Booked</div>
          <div class="metric-val">{rupees(twp.booked_tally)}</div>
          <div class="metric-sub">Books Inward Tax</div>
        </div>
        <div class="metric-card accent">
          <div class="metric-label">Matched Confirmed</div>
          <div class="metric-val">{rupees(twp.matched_tax)}</div>
          <div class="metric-sub">Eligible Backed Credit</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">3B Claimed (Table 4A)</div>
          <div class="metric-val">{rupees(twp.claimed_3b)}</div>
          <div class="metric-sub">Filed Monthly Returns</div>
        </div>
      </div>

      <div class="highlight-banner" style="margin-bottom:18px;background:linear-gradient(135deg,#eff6ff,#dbeafe);border-color:#bfdbfe;">
        <div class="hb-left">
          <span class="hb-tag" style="color:#1d4ed8;">Verified ITC Under-Claim Finding</span>
          <div class="hb-title" style="color:#1e40af;">{rupees(twp.matched_unclaimed)}</div>
          <div class="hb-desc" style="color:#334155;">Invoices 100% matched in both Tally and 2A where credit was legally available, but omitted from GSTR-3B monthly filings.</div>
        </div>
        <div class="hb-badge" style="border-color:#bfdbfe;color:#1e40af;">
          Eligible to Claim<br>
          <strong>Table 8 Gap</strong>
        </div>
      </div>

      <div class="info-callout">
        <strong>The Honesty Caveat:</strong> GSTR-3B Table 4A includes imports, ISD, and reverse-charge credits that do not appear in GSTR-2A's B2B section. This summary does not break those out, so part of the <strong>{rupees(twp.gap_2a_3b)}</strong> total gap between 2A and 3B is legitimately unreconcilable from these files alone.
      </div>
    </div>"""

        m_rows = []
        for mp in twp.monthly:
            d_class = "delta-pos" if mp.variance_3b_2a >= 0 else "delta-neg"
            d_str = f"+Rs {mp.variance_3b_2a:,.2f}" if mp.variance_3b_2a >= 0 else f"-Rs {abs(mp.variance_3b_2a):,.2f}"
            m_rows.append(f"<tr><td><strong>{mp.month}</strong></td><td class=n>Rs {mp.tax_2a_by_invoice_date:,.2f}</td><td class=n>Rs {mp.tax_2a_by_filing_period:,.2f}</td><td class=n>Rs {mp.tally_tax:,.2f}</td><td class=n>Rs {mp.gstr3b_claimed:,.2f}</td><td class=\"n {d_class}\">{d_str}</td></tr>")

        monthly_card = f"""
    <!-- Month-by-Month Timing Card -->
    <div class="card">
      <div class="card-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
        Month-by-Month Timing Schedule
      </div>
      <div class="card-desc">Exposes credit timing differences &mdash; comparing invoice dates vs supplier filing periods vs 3B claims.</div>
      <table>
        <tr>
          <th>Month</th>
          <th class="n">2A (Inv Date)</th>
          <th class="n">2A (Filing Period)</th>
          <th class="n">Tally Booked</th>
          <th class="n">3B Claimed</th>
          <th class="n">Timing Variance</th>
        </tr>
        {''.join(m_rows)}
      </table>
    </div>"""

    res_page = _RESULT_HTML.replace("/*INJECT_CSS*/", _CSS)
    res_page = res_page.replace("__TOKEN__", token)
    res_page = res_page.replace("__GSTR_ROWS__", str(len(gstr)))
    res_page = res_page.replace("__TALLY_ROWS__", str(len(tally)))
    res_page = res_page.replace("__MATCHED__", str(len(res.pairs)))
    res_page = res_page.replace("__TOTAL_2A__", total_2a_val)
    res_page = res_page.replace("__TOTAL_TALLY__", total_tally_val)
    res_page = res_page.replace("__MATCHED_TAX__", matched_tax_val)
    res_page = res_page.replace("__CLAIM__", rupees(total(claim)))
    res_page = res_page.replace("__CLAIM_N__", str(len(claim)))
    res_page = res_page.replace("__DAYS__", str((ITC_DEADLINE - date.today()).days))
    res_page = res_page.replace("__THREE_WAY_CARD__", three_way_card)
    res_page = res_page.replace("__ROWS__", rows)
    res_page = res_page.replace("__MONTHLY_CARD__", monthly_card)
    res_page = res_page.replace("__SHEET_DESC__", sheet_desc)

    return res_page


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
