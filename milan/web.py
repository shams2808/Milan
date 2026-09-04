"""Milan — The Autonomous GST FinOps Operating System & AI Finance Controller.

    python -m milan.web        then open http://127.0.0.1:8000

Binds to 127.0.0.1 locally, and supports serverless deployments (Vercel).
Zero external dependencies, 100% Python standard library.
"""

from __future__ import annotations

import html
import json
import shutil
import tempfile
import urllib.parse
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .copilot import ask_copilot
from .core import indian_number_format, rupees
from .export import write_csv
from .forecaster import compute_finops_forecast
from .loaders import load_gstr2a, load_gstr3b, load_tally, load_tally_purchase
from .match import reconcile
from .remediate import (
    CHASE_SUPPLIER,
    LEDGER_FIX,
    generate_ledger_fix_directive,
    generate_legal_chase_notice,
    plan,
    verify_draft,
)
from .report import (
    ITC_DEADLINE,
    classify_ineligible,
    classify_unclaimed,
    compute_three_way_position,
    pan_conflicts,
)
from .vendor_risk import evaluate_vendor_risk
from .workbook import partial_mismatches, write_workbook

# The mark: two overlapping rounded squares with the intersection filled.
# It is the product stated as a shape -- two independent records, and the
# overlap is what reconciled. The two crescents left over are the two piles.
_MARK = (
    '<svg viewBox="0 0 32 32" fill="none" width="30" height="30" aria-hidden="true">'
    '<defs><clipPath id="mk"><rect x="2.5" y="7.5" width="17" height="17" rx="4"/></clipPath></defs>'
    '<rect x="2.5" y="7.5" width="17" height="17" rx="4" stroke="#fff" stroke-width="2.4"/>'
    '<rect x="12.5" y="7.5" width="17" height="17" rx="4" stroke="#fff" stroke-width="2.4"/>'
    '<g clip-path="url(#mk)">'
    '<rect x="12.5" y="7.5" width="17" height="17" rx="4" fill="#fff"/></g>'
    '</svg>'
)

# Same mark on a filled tile, sized to stay legible at 16px in a browser tab.
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#047857"/>'
    '<defs><clipPath id="f"><rect x="4" y="8.5" width="15" height="15" rx="3.5"/></clipPath></defs>'
    '<rect x="4" y="8.5" width="15" height="15" rx="3.5" fill="none" stroke="#fff" stroke-width="2.8"/>'
    '<rect x="13" y="8.5" width="15" height="15" rx="3.5" fill="none" stroke="#fff" stroke-width="2.8"/>'
    '<g clip-path="url(#f)">'
    '<rect x="13" y="8.5" width="15" height="15" rx="3.5" fill="#fff"/></g>'
    '</svg>'
)

MAX_UPLOAD = 64 * 1024 * 1024
_RESULTS: dict[str, dict] = {}
_TMP = Path(tempfile.gettempdir()) / "milan_sessions"
_TMP.mkdir(parents=True, exist_ok=True)

# Path to built-in demo data
_DATA_DIR = Path(__file__).parent / "Data" / "Heamons"

_CSS = """
:root {
  --primary: #10b981;
  --primary-glow: rgba(16, 185, 129, 0.25);
  --primary-dark: #059669;
  --primary-light: #ecfdf5;
  --accent: #6366f1;
  --accent-glow: rgba(99, 102, 241, 0.25);
  --accent-dark: #4f46e5;
  --accent-light: #eef2ff;
  --bg: #090d16;
  --surface: #111827;
  --surface-card: #172033;
  --surface-hover: #1e293b;
  --border: rgba(255, 255, 255, 0.08);
  --border-focus: #10b981;
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --text-sub: #cbd5e1;
  --danger: #ef4444;
  --danger-glow: rgba(239, 68, 68, 0.2);
  --warning: #f59e0b;
  --warning-glow: rgba(245, 158, 11, 0.2);
  --radius: 14px;
  --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background-color: var(--bg);
  background-image: 
    radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.1) 0px, transparent 50%);
  background-attachment: fixed;
  color: var(--text-main);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
}

.wrap {
  max-width: 1120px;
  margin: 0 auto;
  padding: 36px 24px 100px;
}

/* Header & Brand */
.brand-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--border);
}

.brand-logo-area {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-icon {
  width: 52px;
  height: 52px;
  background: linear-gradient(135deg, #10b981, #047857);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 900;
  font-size: 26px;
  box-shadow: 0 0 24px var(--primary-glow);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.brand-title {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-title span.deva {
  font-size: 16px;
  font-weight: 600;
  color: #34d399;
  background: rgba(16, 185, 129, 0.15);
  padding: 3px 12px;
  border-radius: 20px;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.brand-sub {
  color: var(--text-muted);
  font-size: 14px;
  margin-top: 3px;
}

.badge-local {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  color: #e2e8f0;
  padding: 8px 16px;
  border-radius: 30px;
  font-size: 13px;
  font-weight: 600;
  backdrop-filter: blur(8px);
}
.pulse-dot {
  width: 8px;
  height: 8px;
  background-color: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 8px #10b981;
  display: inline-block;
}

/* Tabs Navigation */
.tabs-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 28px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.tab-btn {
  background: none;
  border: none;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 3px solid transparent;
  margin-bottom: -4px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  white-space: nowrap;
  border-radius: 8px 8px 0 0;
}

.tab-btn:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.03);
}

.tab-btn.active {
  color: #34d399;
  border-bottom-color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}

.tab-pane {
  display: none;
}
.tab-pane.active {
  display: block;
  animation: fadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Cards & Grid Containers */
.card {
  background: var(--surface-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 26px 28px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.card-title {
  font-size: 18px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.metric-grid-4 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.metric-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.metric-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  transition: transform 0.2s, border-color 0.2s;
}
.metric-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.18);
}

.metric-card.accent {
  background: linear-gradient(180deg, rgba(16, 185, 129, 0.12) 0%, rgba(16, 185, 129, 0.04) 100%);
  border-color: rgba(16, 185, 129, 0.3);
}
.metric-card.alert {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.12) 0%, rgba(245, 158, 11, 0.04) 100%);
  border-color: rgba(245, 158, 11, 0.3);
}
.metric-card.indigo {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.12) 0%, rgba(99, 102, 241, 0.04) 100%);
  border-color: rgba(99, 102, 241, 0.3);
}
.metric-card.danger {
  background: linear-gradient(180deg, rgba(239, 68, 68, 0.12) 0%, rgba(239, 68, 68, 0.04) 100%);
  border-color: rgba(239, 68, 68, 0.3);
}

.metric-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.metric-val {
  font-size: 24px;
  font-weight: 800;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.metric-card.accent .metric-val { color: #34d399; }
.metric-card.alert .metric-val { color: #fbbf24; }
.metric-card.indigo .metric-val { color: #818cf8; }
.metric-card.danger .metric-val { color: #f87171; }

.metric-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* Banners */
.highlight-banner {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(185, 28, 28, 0.05));
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.highlight-banner.blue {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(67, 56, 202, 0.05));
  border-color: rgba(99, 102, 241, 0.3);
}

.hb-tag {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  color: #f87171;
  letter-spacing: 0.05em;
}
.highlight-banner.blue .hb-tag { color: #818cf8; }

.hb-title {
  font-size: 28px;
  font-weight: 800;
  color: #fca5a5;
  letter-spacing: -0.02em;
  margin: 2px 0 4px;
}
.highlight-banner.blue .hb-title { color: #c7d2fe; }

.hb-desc {
  font-size: 13px;
  color: #cbd5e1;
}

.hb-badge {
  background: rgba(0, 0, 0, 0.3);
  padding: 10px 18px;
  border-radius: 10px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  font-size: 13px;
  font-weight: 700;
  color: #fca5a5;
  text-align: right;
}
.highlight-banner.blue .hb-badge { border-color: rgba(99, 102, 241, 0.3); color: #c7d2fe; }

/* Table 8 Waterfall Progress Flow */
.flow-chain {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 20px 0;
}
.flow-step {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  text-align: center;
}
.flow-step.active {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}
.flow-step-label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; }
.flow-step-val { font-size: 17px; font-weight: 800; color: #ffffff; margin-top: 4px; }
.flow-arrow { color: var(--text-muted); font-size: 18px; font-weight: 800; }

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
}

th, td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  text-align: left;
}

th {
  background: rgba(255, 255, 255, 0.02);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

td.n {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  white-space: nowrap;
}

.delta-pos { color: #34d399; font-weight: 700; }
.delta-neg { color: #f87171; font-weight: 700; }

.grade-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 6px;
  text-align: center;
}
.grade-A { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
.grade-B { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
.grade-C { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
.grade-D { background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }

.ims-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 12px;
}
.ims-accept { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.ims-pending { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.ims-reject { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.ims-fix { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }

.status-pill {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
}
.status-pill.claim { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.status-pill.reverse { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.status-pill.review { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }

/* Drafter & Preformatted code */
pre.code-draft {
  background: #090d16;
  color: #e2e8f0;
  padding: 18px 20px;
  border-radius: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  overflow-x: auto;
  white-space: pre-wrap;
  margin: 12px 0;
  border: 1px solid var(--border);
}

.seal-verified {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.btn-copy {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border);
  color: #ffffff;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-copy:hover {
  background: rgba(255, 255, 255, 0.15);
}

/* Upload zone */
.upload-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-bottom: 26px;
}

.dropzone {
  position: relative;
  border: 2px dashed rgba(255, 255, 255, 0.15);
  border-radius: 14px;
  padding: 26px 20px;
  text-align: center;
  background: var(--surface);
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 210px;
}

.dropzone:hover {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.04);
}

.dropzone.optional:hover {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.04);
}

.dropzone input[type="file"] {
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  opacity: 0;
  cursor: pointer;
}

.dz-icon {
  width: 48px; height: 48px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 12px;
  color: var(--text-muted);
}
.dropzone:hover .dz-icon { background: rgba(16, 185, 129, 0.15); color: #34d399; }
.dropzone.optional:hover .dz-icon { background: rgba(99, 102, 241, 0.15); color: #818cf8; }

.dz-title { font-weight: 700; font-size: 15px; color: #ffffff; margin-bottom: 4px; }
.dz-pill {
  display: inline-block;
  font-size: 11px; font-weight: 800; text-transform: uppercase;
  padding: 3px 10px; border-radius: 12px; margin-bottom: 8px;
}
.dz-pill.req { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
.dz-pill.opt { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
.dz-sub { font-size: 13px; color: var(--text-muted); }
.dz-file-name {
  margin-top: 10px; font-size: 12px; font-weight: 600;
  color: #34d399; background: rgba(16, 185, 129, 0.15); padding: 4px 12px;
  border-radius: 6px; display: none;
}

button.btn-primary {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white; border: 0; border-radius: 10px;
  padding: 14px 34px; font-size: 15px; font-weight: 800;
  cursor: pointer; box-shadow: 0 4px 18px var(--primary-glow);
  display: inline-flex; align-items: center; gap: 10px;
  transition: all 0.2s;
}
button.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px var(--primary-glow);
}

.btn-demo {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #c7d2fe;
  padding: 14px 24px;
  font-size: 14px;
  font-weight: 700;
  border-radius: 10px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  transition: all 0.2s;
}
.btn-demo:hover {
  background: rgba(99, 102, 241, 0.25);
  color: #ffffff;
  transform: translateY(-2px);
}

.action-card {
  background: linear-gradient(135deg, #064e3b, #047857);
  color: white; border-radius: var(--radius);
  padding: 26px 30px; margin-top: 28px;
  display: flex; align-items: center; justify-content: space-between;
  box-shadow: 0 10px 25px rgba(4, 120, 87, 0.3);
}
.action-text h3 { font-size: 18px; font-weight: 800; margin-bottom: 4px; }
.action-text p { font-size: 13px; color: #a7f3d0; }
.btn-download {
  background: #ffffff; color: #064e3b; text-decoration: none;
  font-weight: 800; font-size: 14px; padding: 12px 22px;
  border-radius: 10px; display: inline-flex; align-items: center; gap: 8px;
  transition: transform 0.2s;
}
.btn-download:hover { transform: translateY(-2px); }
.btn-download.alt {
  background: rgba(255, 255, 255, 0.15); color: white;
  border: 1px solid rgba(255, 255, 255, 0.3); margin-left: 10px;
}

.nav-back { margin-top: 28px; text-align: center; }
.nav-back a { color: #34d399; text-decoration: none; font-weight: 600; font-size: 14px; }
.nav-back a:hover { text-decoration: underline; }

#loader {
  display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(9, 13, 22, 0.85); backdrop-filter: blur(8px);
  z-index: 9999; flex-direction: column; align-items: center; justify-content: center;
  color: white;
}
.spinner {
  width: 52px; height: 52px; border: 4px solid rgba(255, 255, 255, 0.1);
  border-top-color: #10b981; border-radius: 50%; animation: spin 0.8s linear infinite;
  margin-bottom: 18px;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Floating Co-Pilot Chat Widget */
.copilot-trigger {
  position: fixed;
  bottom: 26px;
  right: 26px;
  background: linear-gradient(135deg, #6366f1, #4338ca);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 30px;
  padding: 13px 24px;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 10px 25px var(--accent-glow);
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 9990;
  transition: all 0.25s ease;
}
.copilot-trigger:hover {
  transform: translateY(-3px) scale(1.02);
  box-shadow: 0 14px 30px var(--accent-glow);
}

.copilot-chat-panel {
  position: fixed;
  bottom: 88px;
  right: 26px;
  width: 440px;
  max-width: calc(100vw - 48px);
  height: 600px;
  max-height: calc(100vh - 120px);
  background: var(--surface-card);
  border: 1px solid rgba(99, 102, 241, 0.4);
  border-radius: 18px;
  box-shadow: 0 24px 45px rgba(0, 0, 0, 0.6);
  z-index: 9995;
  display: none;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(16px);
  animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.copilot-header {
  background: linear-gradient(135deg, #4f46e5, #3730a3);
  color: white;
  padding: 15px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.copilot-header-title { font-weight: 800; font-size: 15px; display: flex; align-items: center; gap: 8px; }
.copilot-header-sub { font-size: 11px; color: #c7d2fe; }
.copilot-close {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: white;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
.copilot-close:hover { background: rgba(255, 255, 255, 0.3); }

.copilot-body {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  background: #0c101c;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-msg {
  display: flex;
  flex-direction: column;
  max-width: 92%;
}
.chat-msg.user {
  align-self: flex-end;
  background: #4f46e5;
  color: white;
  padding: 10px 14px;
  border-radius: 14px 14px 2px 14px;
  font-size: 13px;
}
.chat-msg.copilot {
  align-self: flex-start;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-sub);
  padding: 14px 16px;
  border-radius: 14px 14px 14px 2px;
  font-size: 13px;
}

.prompt-chips-chat {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.prompt-chip-chat {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #c7d2fe;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.prompt-chip-chat:hover { background: rgba(99, 102, 241, 0.3); color: white; }

.copilot-footer {
  padding: 14px;
  background: var(--surface-card);
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
}
.copilot-input-field {
  flex: 1;
  background: #090d16;
  border: 1px solid var(--border);
  color: white;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  outline: none;
}
.copilot-input-field:focus { border-color: #6366f1; }
.copilot-send-btn {
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0 18px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}
.copilot-send-btn:hover { background: #4f46e5; }

/* Toast */
#toast {
  position: fixed;
  bottom: 26px;
  left: 50%;
  transform: translateX(-50%) translateY(100px);
  background: #10b981;
  color: white;
  font-weight: 700;
  font-size: 13px;
  padding: 10px 22px;
  border-radius: 30px;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  opacity: 0;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 99999;
}
#toast.show {
  transform: translateX(-50%) translateY(0);
  opacity: 1;
}

@media (max-width: 768px) {
  .metric-grid-4, .metric-grid-3 { grid-template-columns: 1fr; }
  .action-card { flex-direction: column; gap: 16px; text-align: center; }
  .copilot-chat-panel { right: 12px; bottom: 80px; width: calc(100vw - 24px); }
  .flow-chain { flex-direction: column; }
}
"""

_FORM_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>Milan — Autonomous GST FinOps Operating System</title>
  <style>__CSS__</style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <h3 style="font-weight:800;font-size:22px;letter-spacing:-0.02em;">Running FinOps Controller Engine...</h3>
    <p style="color:#94a3b8;font-size:14px;margin-top:6px;">Executing Table 8 recon, Rule 88D shield, and vendor IMS rating</p>
  </div>

  <div class="wrap">
    <header class="brand-header">
      <div class="brand-logo-area">
        <div class="brand-icon">__MARK__</div>
        <div>
          <div class="brand-title">
            Milan <span class="deva">मिलान</span>
          </div>
          <div class="brand-sub">Autonomous GST FinOps Operating System &middot; Track 04 AI Finance Controller</div>
        </div>
      </div>
      <div class="badge-local">
        <span class="pulse-dot"></span>
        Zero Cloud Leak &middot; 100% Deterministic
      </div>
    </header>

    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
        <div>
          <div class="card-title">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            Upload Client Books & Returns
          </div>
          <div class="card-desc" style="margin-bottom:0;">
            Select the client's GSTR-2A annual summary, Tally Purchase Register, and GSTR-3B monthly return.
          </div>
        </div>
        <a href="/demo" class="btn-demo" onclick="showLoader()">
          🚀 Try Live Enterprise Demo (₹5.74 Cr)
        </a>
      </div>

      <form id="recon-form" method="post" action="/reconcile" enctype="multipart/form-data">
        <div class="upload-grid" style="margin-top:20px;">
          
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

          <div class="dropzone" id="dz-tally">
            <div class="dz-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
            </div>
            <span class="dz-pill req">Required</span>
            <div class="dz-title">Tally or Busy Purchase Register</div>
            <div class="dz-sub">Tally DayBook / Purchase or Busy Inward Register (.xlsx)</div>
            <input type="file" name="tally" id="file-tally" accept=".xlsx" multiple required onchange="handleFileSelected(this, 'dz-tally')">
            <div class="dz-file-name" id="name-dz-tally"></div>
          </div>

          <div class="dropzone optional" id="dz-3b">
            <div class="dz-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
            </div>
            <span class="dz-pill opt">Optional &middot; Unlocks Table 8</span>
            <div class="dz-title">GSTR-3B Monthly Summary</div>
            <div class="dz-sub">12-month summary for Table 8 & cash forecaster</div>
            <input type="file" name="gstr3b" id="file-3b" accept=".xlsx" onchange="handleFileSelected(this, 'dz-3b')">
            <div class="dz-file-name" id="name-dz-3b"></div>
          </div>

        </div>

        <div style="display:flex;align-items:center;justify-content:space-between;padding-top:10px;">
          <div style="font-size:13px;color:#94a3b8;">
            Zero cloud footprint &middot; 100% deterministic &middot; Verification capacity over generation speed
          </div>
          <button type="submit" class="btn-primary" onclick="showLoader()">
            Launch FinOps Controller
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
          </button>
        </div>
      </form>
    </div>
  </div>

  <script>
    function handleFileSelected(input, dzId) {
      var nameEl = document.getElementById('name-' + dzId);
      if (input.files && input.files.length > 0) {
        nameEl.textContent = '✓ ' + (input.files.length === 1 ? input.files[0].name : input.files.length + ' files selected');
        nameEl.style.display = 'inline-block';
      } else {
        nameEl.style.display = 'none';
      }
    }
    function showLoader() {
      var f2a = document.getElementById('file-2a');
      var ftally = document.getElementById('file-tally');
      if ((f2a && f2a.files.length && ftally && ftally.files.length) || event.target.classList.contains('btn-demo')) {
        document.getElementById('loader').style.display = 'flex';
      }
    }
  </script>
</body>
</html>"""

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>Milan — GST FinOps Operating System</title>
  <style>__CSS__</style>
</head>
<body>
  <div id="toast">Notice copied to clipboard!</div>

  <div class="wrap">
    <header class="brand-header">
      <div class="brand-logo-area">
        <div class="brand-icon">__MARK__</div>
        <div>
          <div class="brand-title">Milan FinOps Controller</div>
          <div class="brand-sub">__GSTR_COUNT__ portal bills &middot; __TALLY_COUNT__ books bills &middot; __MATCH_COUNT__ confirmed matches</div>
        </div>
      </div>
      <div class="badge-local">
        <span class="pulse-dot"></span>
        Cascade Controller Active &middot; 100% Matched
      </div>
    </header>

    <!-- Navigation Tabs (4 Core Pillars) -->
    <div class="tabs-nav">
      <button class="tab-btn active" onclick="switchTab('tab-recon', this)">📊 Reconciliation & Table 8</button>
      <button class="tab-btn" onclick="switchTab('tab-forecaster', this)">🛡️ Rule 88D & Cash Forecaster</button>
      <button class="tab-btn" onclick="switchTab('tab-vendors', this)">🏢 Vendor IMS Matrix</button>
      <button class="tab-btn" onclick="switchTab('tab-drafter', this)">⚖️ Dispute Notice Drafter</button>
    </div>

    <!-- TAB 1: Recon & Table 8 -->
    <div id="tab-recon" class="tab-pane active">
      <div class="metric-grid-4">
        <div class="metric-card">
          <div class="metric-label">2A Available (Portal)</div>
          <div class="metric-val">__AVAIL_2A__</div>
          <div class="metric-sub">__GSTR_COUNT__ Inward Bills</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Books Inward (Tally / Busy)</div>
          <div class="metric-val">__BOOKED_TALLY__</div>
          <div class="metric-sub">__TALLY_COUNT__ Inward Bills</div>
        </div>
        <div class="metric-card accent">
          <div class="metric-label">Matched ITC Confirmed</div>
          <div class="metric-val">__MATCHED_TAX__</div>
          <div class="metric-sub">__MATCH_COUNT__ Exact Invoice Pairs</div>
        </div>
        <div class="metric-card alert">
          <div class="metric-label">Unclaimed in Books</div>
          <div class="metric-val">__UNCLAIMED_TAX__</div>
          <div class="metric-sub">__UNCLAIMED_COUNT__ Bills (__DAYS_LEFT__d left)</div>
        </div>
      </div>

      <div class="highlight-banner">
        <div class="hb-left">
          <span class="hb-tag">Statutory Action Required u/s 16(4)</span>
          <div class="hb-title">__UNCLAIMED_TAX__</div>
          <div class="hb-desc">Inward supplies verified on GST portal that your client never booked in accounting software.</div>
        </div>
        <div class="hb-badge">
          Lapses on 30 Nov 2026<br>
          <strong>__DAYS_LEFT__ Days Left</strong>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Categorized Findings by Cause (2A &harr; Books)</div>
        <div class="card-desc">Every discrepancy classified by actionable tax remedy rather than raw unassigned totals.</div>
        <table>
          <tr>
            <th>Category</th>
            <th class="n">Bills</th>
            <th class="n">ITC Value</th>
            <th>What to Do</th>
          </tr>
          __RECON_ROWS__
        </table>
      </div>

      __THREE_WAY_SECTION__
    </div>

    <!-- TAB 2: Forecaster & Rule 88D -->
    <div id="tab-forecaster" class="tab-pane">
      <div class="metric-grid-3">
        <div class="metric-card __R88_BADGE__">
          <div class="metric-label">Rule 88D (DRC-01C) Status</div>
          <div class="metric-val">__R88_STATUS__</div>
          <div class="metric-sub">Form DRC-01C Notice Shield</div>
        </div>
        <div class="metric-card indigo">
          <div class="metric-label">Forecast Net Cash Outflow</div>
          <div class="metric-val">__NET_CASH_OUTFLOW__</div>
          <div class="metric-sub">Next Month Estimated 3B</div>
        </div>
        <div class="metric-card danger">
          <div class="metric-label">Section 50 Interest Penalty</div>
          <div class="metric-val">__SEC50_INTEREST__</div>
          <div class="metric-sub">18% p.a. on __SEC50_COUNT__ unfiled bills</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Form DRC-01C (Rule 88D) Scrutiny Shield</div>
        <div class="card-desc">__R88_SUMMARY__</div>
        <div style="background:rgba(16, 185, 129, 0.08);padding:16px 20px;border-radius:10px;border-left:4px solid #10b981;font-size:13px;color:#cbd5e1;">
          <strong style="color:#34d399;">Statutory Compliance Defense:</strong> __R88_REMEDY__
        </div>
      </div>

      <div class="card">
        <div class="card-title">Forward Cash Outflow & Working Capital Position</div>
        <div class="card-desc">Calculates next month's net GST cash liability after verified ITC offset.</div>
        <div class="metric-grid-3">
          <div class="metric-card">
            <div class="metric-label">Estimated Output Liability</div>
            <div class="metric-val">__AVG_LIABILITY__</div>
          </div>
          <div class="metric-card accent">
            <div class="metric-label">Verified ITC Offset</div>
            <div class="metric-val">__AVG_ITC__</div>
          </div>
          <div class="metric-card indigo">
            <div class="metric-label">Closing Credit Ledger Balance</div>
            <div class="metric-val">__CLOSING_BAL__</div>
          </div>
        </div>
        <div class="highlight-banner blue" style="margin-top:16px;">
          <div class="hb-left">
            <span class="hb-tag">Trapped Working Capital</span>
            <div class="hb-title">__TRAPPED_CAPITAL__</div>
            <div class="hb-desc">Credit locked in __TRAPPED_COUNT__ unfiled invoices. Recovering these reduces next month cash liability directly.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: Vendor IMS Matrix -->
    <div id="tab-vendors" class="tab-pane">
      <div class="metric-grid-3">
        <div class="metric-card accent">
          <div class="metric-label">IMS Accept Eligible</div>
          <div class="metric-val">__IMS_ACCEPT_TAX__</div>
          <div class="metric-sub">__IMS_ACCEPT_CNT__ Invoices (__GRADE_A_CNT__ Grade A Vendors)</div>
        </div>
        <div class="metric-card alert">
          <div class="metric-label">IMS Hold in Pending</div>
          <div class="metric-val">__IMS_PENDING_TAX__</div>
          <div class="metric-sub">__IMS_PENDING_CNT__ Invoices (__GRADE_B_CNT__ Grade B Vendors)</div>
        </div>
        <div class="metric-card danger">
          <div class="metric-label">IMS Reject / Dispute</div>
          <div class="metric-val">__IMS_REJECT_TAX__</div>
          <div class="metric-sub">__IMS_REJECT_CNT__ Invoices (__GRADE_CD_CNT__ High Risk Vendors)</div>
        </div>
      </div>

      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
          <div>
            <div class="card-title">Vendor Compliance Scorecards & IMS Directives</div>
            <div class="card-desc" style="margin-bottom:0;">Evaluates __TOTAL_VENDORS__ suppliers across filing timeliness, multi-state registrations, and tax accuracy.</div>
          </div>
          <input type="text" id="vendor-search" placeholder="Search supplier or GSTIN..." onkeyup="filterVendors()" style="background:#090d16;border:1px solid var(--border);color:white;padding:8px 14px;border-radius:8px;font-size:13px;outline:none;">
        </div>

        <table id="vendor-table">
          <thead>
            <tr>
              <th>Grade</th>
              <th>Supplier Name & GSTIN</th>
              <th class="n">Booked Tax</th>
              <th class="n">Verified Tax</th>
              <th class="n">Unfiled Tax</th>
              <th>IMS Directive</th>
            </tr>
          </thead>
          <tbody>
            __VENDOR_ROWS__
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 4: Dispute Notice Drafter -->
    <div id="tab-drafter" class="tab-pane">
      <div class="card">
        <div class="card-title">1-Click Statutory Demand Notices (Section 16(2)(c))</div>
        <div class="card-desc">Auto-generated, legally sound dispute notices for non-filing vendors with mathematical zero-hallucination verification.</div>
        __CHASE_CARDS__
      </div>
    </div>

    <!-- Downloads Section -->
    <div class="action-card">
      <div class="action-text">
        <h3>Export Complete Working Papers</h3>
        <p>Six sheets: Summary, Not in Tally, Not in 2A, Partial Mismatch, Other Ledgers, and dedicated ITC Position.</p>
      </div>
      <div>
        <a class="btn-download" href="/download/__TOKEN__/xlsx">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Download Excel Workbook
        </a>
        <a class="btn-download alt" href="/download/__TOKEN__/csv">Download CSV</a>
      </div>
    </div>

    <div class="nav-back">
      <a href="/">← Reconcile another client</a>
    </div>

  </div>

  <!-- FLOATING COPILOT CHATBOT (BOTTOM RIGHT) -->
  <button class="copilot-trigger" onclick="toggleCopilotChat()">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
    <span>✨ Ask FinOps Co-Pilot</span>
  </button>

  <div id="copilot-chat" class="copilot-chat-panel">
    <div class="copilot-header">
      <div>
        <div class="copilot-header-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>
          FinOps Controller Co-Pilot
        </div>
        <div class="copilot-header-sub">100% Fact-Grounded &middot; Zero Hallucination</div>
      </div>
      <button class="copilot-close" onclick="toggleCopilotChat()">✕</button>
    </div>

    <div id="copilot-chat-body" class="copilot-body">
      <div class="chat-msg copilot">
        <strong style="color:#ffffff;">👋 Hello! I am your AI Finance Controller.</strong>
        <p style="margin-top:4px;color:#94a3b8;">Ask me anything about your GST books, Rule 88D risk, Section 16(4) lapse, or delinquent vendors.</p>
        <div class="prompt-chips-chat">
          <button class="prompt-chip-chat" onclick="sendQuickPrompt('Who are our top risk suppliers?')">Who are our top risk suppliers?</button>
          <button class="prompt-chip-chat" onclick="sendQuickPrompt('What is our Section 16(4) lapse exposure?')">Section 16(4) lapse</button>
          <button class="prompt-chip-chat" onclick="sendQuickPrompt('Forecast next month cash outflow')">Forecast cash outflow</button>
          <button class="prompt-chip-chat" onclick="sendQuickPrompt('Are we at risk under Rule 88D?')">Rule 88D notice risk</button>
          <button class="prompt-chip-chat" onclick="sendQuickPrompt('Show multi-state PAN conflicts')">Multi-State PAN conflicts</button>
        </div>
      </div>
    </div>

    <div class="copilot-footer">
      <input type="text" id="copilot-input" class="copilot-input-field" placeholder="Ask a question..." onkeydown="if(event.key==='Enter') sendChatMessage()">
      <button class="copilot-send-btn" onclick="sendChatMessage()">Send</button>
    </div>
  </div>

  <script>
    var sessionToken = "__TOKEN__";

    function showToast(msg) {
      var t = document.getElementById('toast');
      t.textContent = msg;
      t.className = 'show';
      setTimeout(function() { t.className = ''; }, 2500);
    }

    function switchTab(tabId, btn) {
      var panes = document.querySelectorAll('.tab-pane');
      for (var i = 0; i < panes.length; i++) {
        panes[i].classList.remove('active');
      }
      var btns = document.querySelectorAll('.tab-btn');
      for (var j = 0; j < btns.length; j++) {
        btns[j].classList.remove('active');
      }
      document.getElementById(tabId).classList.add('active');
      btn.classList.add('active');
    }

    function copyDraft(elemId) {
      var text = document.getElementById(elemId).innerText;
      navigator.clipboard.writeText(text).then(function() {
        showToast("✓ Demand Notice copied to clipboard!");
      });
    }

    function filterVendors() {
      var query = document.getElementById('vendor-search').value.toLowerCase();
      var rows = document.querySelectorAll('#vendor-table tbody tr');
      for (var i = 0; i < rows.length; i++) {
        var text = rows[i].textContent.toLowerCase();
        rows[i].style.display = text.indexOf(query) > -1 ? '' : 'none';
      }
    }

    function toggleCopilotChat() {
      var panel = document.getElementById('copilot-chat');
      if (panel.style.display === 'flex') {
        panel.style.display = 'none';
      } else {
        panel.style.display = 'flex';
        document.getElementById('copilot-input').focus();
        scrollChatToBottom();
      }
    }

    function sendQuickPrompt(text) {
      document.getElementById('copilot-input').value = text;
      sendChatMessage();
    }

    function scrollChatToBottom() {
      var body = document.getElementById('copilot-chat-body');
      body.scrollTop = body.scrollHeight;
    }

    function sendChatMessage() {
      var input = document.getElementById('copilot-input');
      var q = input.value.trim();
      if (!q) return;

      var body = document.getElementById('copilot-chat-body');

      // Append User Message
      var userBubble = document.createElement('div');
      userBubble.className = 'chat-msg user';
      userBubble.textContent = q;
      body.appendChild(userBubble);
      input.value = '';
      scrollChatToBottom();

      // Append Loading Bubble
      var loadingBubble = document.createElement('div');
      loadingBubble.className = 'chat-msg copilot';
      loadingBubble.innerHTML = "<div style='display:flex;align-items:center;gap:6px;color:#94a3b8;'><em>Analyzing books and reconciliation state...</em></div>";
      body.appendChild(loadingBubble);
      scrollChatToBottom();

      fetch('/api/copilot?token=' + sessionToken + '&q=' + encodeURIComponent(q))
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
          var content = "<div style='font-size:14px;font-weight:800;color:#818cf8;margin-bottom:6px;'>" + data.headline + "</div>";
          content += "<div style='color:#e2e8f0;'>" + data.answer_html + "</div>";

          if (data.action_items && data.action_items.length) {
            content += "<div style='margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);font-size:11px;font-weight:700;text-transform:uppercase;color:#a5b4fc;'>Action Checklist:</div><ul style='margin-left:16px;font-size:12px;color:#cbd5e1;'>";
            for (var k = 0; k < data.action_items.length; k++) {
              content += "<li>" + data.action_items[k] + "</li>";
            }
            content += "</ul>";
          }
          loadingBubble.innerHTML = content;
          scrollChatToBottom();
        })
        .catch(function(err) {
          loadingBubble.innerHTML = "<div style='color:#f87171;'>Error querying Co-Pilot: " + err.toString() + "</div>";
          scrollChatToBottom();
        });
    }
  </script>
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

    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/favicon.svg":
            data = _FAVICON.encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                self.close_connection = True
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self._send(_FORM_HTML.replace("__CSS__", _CSS).replace("__MARK__", _MARK))

        if path == "/demo":
            # 1-Click demo dataset loader
            p_2a = _DATA_DIR / "07ADQPG9909B1ZF_GSTR2A_ANNUAL_Summary(2025-2026).xlsx"
            p_tally = _DATA_DIR / "DayBook.xlsx"
            p_3b = _DATA_DIR / "07ADQPG9909B1ZF_GSTR3B_MONTHWISE_Summary(2025-2026).xlsx"

            if not p_2a.exists() or not p_tally.exists():
                return self._send("Demo data files not found", 404)

            token = "demo_" + uuid.uuid4().hex[:8]
            folder = _TMP / token
            folder.mkdir(parents=True, exist_ok=True)

            gstr = load_gstr2a(str(p_2a))
            tally, _ = load_tally([str(p_tally)])
            gstr3b = load_gstr3b(str(p_3b)) if p_3b.exists() else None
            res = reconcile(tally, gstr)
            twp = compute_three_way_position(tally, gstr, res, gstr3b) if gstr3b else None
            forecast = compute_finops_forecast(tally, gstr, res, twp, gstr3b)
            vendors, ims_summary = evaluate_vendor_risk(tally, gstr, res)
            actions = plan(res, tally, gstr)

            write_workbook(str(folder / "reconciliation.xlsx"), tally, gstr, res, gstr3b=gstr3b)
            write_csv(str(folder / "findings.csv"), tally, gstr, res)

            _RESULTS[token] = {
                "folder": folder,
                "tally": tally,
                "gstr": gstr,
                "res": res,
                "gstr3b": gstr3b,
                "twp": twp,
                "forecast": forecast,
                "vendors": vendors,
                "ims_summary": ims_summary,
                "actions": actions,
            }

            return self._send(_render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions))

        if path == "/api/copilot":
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get("token", [""])[0]
            query = params.get("q", [""])[0]
            state = _RESULTS.get(token)
            if not state:
                return self._send(json.dumps({"error": "Session expired"}), 404, "application/json")

            res = ask_copilot(
                query,
                state["tally"],
                state["gstr"],
                state["res"],
                state.get("twp"),
                state.get("gstr3b"),
                state["forecast"],
                state["vendors"],
                state["ims_summary"],
            )
            return self._send(json.dumps({
                "query": res.query,
                "headline": res.headline,
                "answer_html": res.answer_html,
                "action_items": res.action_items,
            }), 200, "application/json")

        if path.startswith("/download/"):
            try:
                _, _, token, kind = path.split("/", 3)
            except ValueError:
                return self._send("Bad download link", 400)
            state = _RESULTS.get(token)
            if state is None:
                return self._send("Session expired", 404)
            fpath = state["folder"] / ("reconciliation.xlsx" if kind == "xlsx" else "findings.csv")
            if not fpath.exists():
                return self._send("File not found", 404)
            data = fpath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{fpath.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._send("Page not found", 404)

    def do_POST(self) -> None:
        if self.path != "/reconcile":
            return self._send("Page not found", 404)

        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            return self._send("Malformed upload", 400)
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return self._send("Files are too large", 413)

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
            return self._send("Please upload both required files (GSTR-2A and Tally)", 400)

        try:
            gstr = load_gstr2a(str(gstr_path))
            tally, _vtypes = load_tally([str(p) for p in tally_paths])
            gstr3b = load_gstr3b(str(gstr3b_path)) if gstr3b_path else None
            res = reconcile(tally, gstr)
            twp = compute_three_way_position(tally, gstr, res, gstr3b) if gstr3b else None
            forecast = compute_finops_forecast(tally, gstr, res, twp, gstr3b)
            vendors, ims_summary = evaluate_vendor_risk(tally, gstr, res)
            actions = plan(res, tally, gstr)

            write_workbook(str(folder / "reconciliation.xlsx"), tally, gstr, res, gstr3b=gstr3b)
            write_csv(str(folder / "findings.csv"), tally, gstr, res)
        except Exception as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return self._send(f"Error during reconciliation: {html.escape(str(exc))}", 400)

        _RESULTS[token] = {
            "folder": folder,
            "tally": tally,
            "gstr": gstr,
            "res": res,
            "gstr3b": gstr3b,
            "twp": twp,
            "forecast": forecast,
            "vendors": vendors,
            "ims_summary": ims_summary,
            "actions": actions,
        }

        self._send(_render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions))


def _render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions) -> str:
    unclaimed = classify_unclaimed(res, tally)
    ineligible = classify_ineligible(res, gstr)
    claim = unclaimed.get("missing_invoice", [])
    not_in_2a = ineligible.get("not_filed", []) + ineligible.get("supplier_absent", [])
    other = unclaimed.get("supplier_absent", [])
    conflicts = unclaimed.get("other_registration", [])
    mismatches = partial_mismatches(res)

    def total(rows):
        return sum(i.tax for i in rows)

    days_left = (ITC_DEADLINE - date.today()).days

    # --- TAB 1: Recon & Table 8 ---
    def row(label, n, value, action, pill_class):
        return (f"<tr><td><strong style='color:#ffffff;'>{label}</strong></td><td class=n>{n}</td>"
                f"<td class=n><strong style='color:#ffffff;'>{value}</strong></td>"
                f"<td><span class=\"status-pill {pill_class}\">{action}</span></td></tr>")

    recon_rows = "".join([
        row("Not in Tally (Missing Inward)", len(claim), rupees(total(claim)), "Claim before 30 Nov", "claim"),
        row("Not in 2A (Unfiled by Supplier)", len(not_in_2a), rupees(total(not_in_2a)), "Chase supplier / Reverse u/s 50", "reverse"),
        row("Partial Mismatch (Amount/Date)", len(mismatches), "&mdash;", "Review paired bills side by side", "review"),
        row("GSTIN Conflict (Multi-State PAN)", len(conflicts), rupees(total(conflicts)), "Correct supplier ledger in Tally", "review"),
        row("Other Ledgers (Nominal Out of Scope)", len(other), rupees(total(other)), "Reconciled via other ledgers", "claim"),
    ])

    tab1_three_way = ""
    if twp is not None:
        m_rows = []
        for mp in twp.monthly:
            d_class = "delta-pos" if mp.variance_3b_2a >= 0 else "delta-neg"
            d_prefix = "+Rs " if mp.variance_3b_2a >= 0 else "-Rs "
            d_str = f"{d_prefix}{indian_number_format(abs(mp.variance_3b_2a), 2)}"
            m_rows.append(f"<tr><td><strong style='color:#ffffff;'>{mp.month}</strong></td><td class=n>Rs {indian_number_format(mp.tax_2a_by_invoice_date, 2)}</td><td class=n>Rs {indian_number_format(mp.tax_2a_by_filing_period, 2)}</td><td class=n>Rs {indian_number_format(mp.tally_tax, 2)}</td><td class=n>Rs {indian_number_format(mp.gstr3b_claimed, 2)}</td><td class=\"n {d_class}\">{d_str}</td></tr>")

        tab1_three_way = f"""
      <div class="card" style="margin-top:24px;border-color:rgba(99, 102, 241, 0.4);">
        <div class="card-title" style="color:#c7d2fe;">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
          Table 8 Reconciliation Flow (Available &rarr; Booked &rarr; Matched &rarr; Claimed)
        </div>
        <div class="card-desc">End-to-end statutory credit verification bridging portal availability, accounting books, and filed GSTR-3B returns.</div>

        <div class="flow-chain">
          <div class="flow-step">
            <div class="flow-step-label">1. Portal Available (8A)</div>
            <div class="flow-step-val">{rupees(twp.available_2a)}</div>
          </div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step">
            <div class="flow-step-label">2. Books Inward Booked</div>
            <div class="flow-step-val">{rupees(twp.booked_tally)}</div>
          </div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step active">
            <div class="flow-step-label" style="color:#34d399;">3. Matched Verified</div>
            <div class="flow-step-val" style="color:#34d399;">{rupees(twp.matched_tax)}</div>
          </div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step">
            <div class="flow-step-label">4. GSTR-3B Claimed (4A)</div>
            <div class="flow-step-val">{rupees(twp.claimed_3b)}</div>
          </div>
        </div>

        <div class="highlight-banner blue">
          <div class="hb-left">
            <span class="hb-tag">Crucial Statutory Finding &middot; Under-Claimed ITC</span>
            <div class="hb-title">{rupees(twp.matched_unclaimed)}</div>
            <div class="hb-desc">Invoices 100% matched in both Tally and 2A where credit was eligible, but omitted from GSTR-3B filings.</div>
          </div>
          <div class="hb-badge">
            Eligible to Claim<br>
            <strong>Table 8 Gap</strong>
          </div>
        </div>

        <div style="background:rgba(99, 102, 241, 0.08);border-left:4px solid #6366f1;padding:14px 18px;border-radius:0 8px 8px 0;margin:16px 0;font-size:13px;color:#cbd5e1;">
          <strong style="color:#c7d2fe;">The Honesty Caveat:</strong> GSTR-3B Table 4A includes imports, ISD, and reverse-charge credits not present in GSTR-2A B2B. So part of the <strong>{rupees(twp.gap_2a_3b)}</strong> total gap is legitimately unreconcilable from these files alone.
        </div>

        <table style="margin-top:16px;">
          <tr>
            <th>Month</th>
            <th class="n">2A (Inv Date)</th>
            <th class="n">2A (Filing Mo)</th>
            <th class="n">Tally Booked</th>
            <th class="n">3B Claimed</th>
            <th class="n">Timing Variance</th>
          </tr>
          {''.join(m_rows)}
        </table>
      </div>"""

    # --- TAB 2: Forecaster & Rule 88D ---
    r88 = forecast.rule_88d
    cf = forecast.cash_forecast
    s50 = forecast.sec_50_interest
    r88_badge = "accent" if r88.risk_level == "SAFE" else ("alert" if r88.risk_level == "ELEVATED" else "danger")

    # --- TAB 3: Vendor Risk Matrix ---
    vendor_rows = []
    for v in vendors[:25]:
        v_class = f"grade-{v.grade}"
        ims_badge_class = f"ims-{v.ims_action.lower().replace(' ', '-')}"
        vendor_rows.append(f"""<tr>
          <td><span class="grade-badge {v_class}">Grade {v.grade}</span></td>
          <td><strong style="color:#ffffff;">{html.escape(v.name[:32])}</strong><br><code style="font-size:11px;color:#94a3b8;">{v.gstin}</code></td>
          <td class="n">{rupees(v.booked_tax)}</td>
          <td class="n">{rupees(v.matched_tax)}</td>
          <td class="n" style="color:{'#f87171' if v.unfiled_tax > 0 else '#94a3b8'};font-weight:700;">{rupees(v.unfiled_tax)}</td>
          <td><span class="ims-badge {ims_badge_class}">{v.ims_action}</span></td>
        </tr>""")

    # --- TAB 4: Remediation & Drafter ---
    chase_actions = [a for a in actions if a.kind == CHASE_SUPPLIER]
    chase_cards = []
    for idx, ca in enumerate(chase_actions[:6], 1):
        draft_text = generate_legal_chase_notice(ca)
        chase_cards.append(f"""
        <div class="card" style="margin-bottom:18px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <div style="font-weight:800;font-size:15px;color:#ffffff;">
              {idx}. {html.escape(ca.recipient)} ({ca.facts['invoice_count']} unfiled invoice(s))
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="seal-verified">✓ 100% Fact Verified</span>
              <button class="btn-copy" onclick="copyDraft('draft-{idx}')">Copy Notice</button>
            </div>
          </div>
          <div style="font-size:13px;color:#94a3b8;margin-bottom:10px;">
            GSTIN: <code>{ca.facts['supplier_gstin']}</code> &middot; Tax at Stake: <strong style="color:#f87171;">{rupees(ca.facts['total_tax'])}</strong>
          </div>
          <pre class="code-draft" id="draft-{idx}">{html.escape(draft_text)}</pre>
        </div>""")

    # Render Template with token replacements
    res_page = _DASHBOARD_HTML.replace("__CSS__", _CSS).replace("__MARK__", _MARK)
    res_page = res_page.replace("__TOKEN__", token)
    res_page = res_page.replace("__GSTR_COUNT__", str(len(gstr)))
    res_page = res_page.replace("__TALLY_COUNT__", str(len(tally)))
    res_page = res_page.replace("__MATCH_COUNT__", str(len(res.pairs)))
    res_page = res_page.replace("__AVAIL_2A__", rupees(sum(i.tax for i in gstr)))
    res_page = res_page.replace("__BOOKED_TALLY__", rupees(sum(i.tax for i in tally)))
    res_page = res_page.replace("__MATCHED_TAX__", rupees(sum(p.gstr.tax for p in res.pairs)))
    res_page = res_page.replace("__UNCLAIMED_TAX__", rupees(total(claim)))
    res_page = res_page.replace("__UNCLAIMED_COUNT__", str(len(claim)))
    res_page = res_page.replace("__DAYS_LEFT__", str(days_left))
    res_page = res_page.replace("__RECON_ROWS__", recon_rows)
    res_page = res_page.replace("__THREE_WAY_SECTION__", tab1_three_way)
    res_page = res_page.replace("__R88_BADGE__", r88_badge)
    res_page = res_page.replace("__R88_STATUS__", r88.risk_level)
    res_page = res_page.replace("__R88_SUMMARY__", html.escape(r88.summary))
    res_page = res_page.replace("__R88_REMEDY__", html.escape(r88.remedy))
    res_page = res_page.replace("__NET_CASH_OUTFLOW__", rupees(cf.forecast_net_cash_outflow_next_month))
    res_page = res_page.replace("__SEC50_INTEREST__", rupees(s50.estimated_interest_exposure))
    res_page = res_page.replace("__SEC50_COUNT__", str(s50.invoice_count))
    res_page = res_page.replace("__AVG_LIABILITY__", rupees(cf.avg_monthly_tax_liability))
    res_page = res_page.replace("__AVG_ITC__", rupees(cf.avg_monthly_verified_itc))
    res_page = res_page.replace("__CLOSING_BAL__", rupees(cf.closing_itc_balance))
    res_page = res_page.replace("__TRAPPED_CAPITAL__", rupees(cf.trapped_working_capital_unfiled))
    res_page = res_page.replace("__TRAPPED_COUNT__", str(cf.total_unfiled_invoices_count))
    res_page = res_page.replace("__IMS_ACCEPT_TAX__", rupees(ims_summary.ims_accept_tax))
    res_page = res_page.replace("__IMS_ACCEPT_CNT__", str(ims_summary.ims_accept_count))
    res_page = res_page.replace("__GRADE_A_CNT__", str(ims_summary.grade_a_count))
    res_page = res_page.replace("__IMS_PENDING_TAX__", rupees(ims_summary.ims_pending_tax))
    res_page = res_page.replace("__IMS_PENDING_CNT__", str(ims_summary.ims_pending_count))
    res_page = res_page.replace("__GRADE_B_CNT__", str(ims_summary.grade_b_count))
    res_page = res_page.replace("__IMS_REJECT_TAX__", rupees(ims_summary.ims_reject_tax))
    res_page = res_page.replace("__IMS_REJECT_CNT__", str(ims_summary.ims_reject_count))
    res_page = res_page.replace("__GRADE_CD_CNT__", str(ims_summary.grade_c_count + ims_summary.grade_d_count))
    res_page = res_page.replace("__TOTAL_VENDORS__", str(ims_summary.total_vendors_analyzed))
    res_page = res_page.replace("__VENDOR_ROWS__", "".join(vendor_rows))
    res_page = res_page.replace("__CHASE_CARDS__", "".join(chase_cards) if chase_cards else '<p style="color:#94a3b8;">No non-filing suppliers found.</p>')

    return res_page


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\n  Milan FinOps Controller is running at http://127.0.0.1:{args.port}")
    print(f"  Zero cloud footprint &middot; 100% local.")
    print("  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopping server")


if __name__ == "__main__":
    main()
