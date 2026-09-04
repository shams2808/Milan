"""Milan — The Autonomous GST FinOps Operating System & AI Finance Controller.

    python -m milan.web        then open http://127.0.0.1:8000

Binds to 127.0.0.1 locally, and supports serverless deployments (Vercel).
Zero external dependencies, 100% Python standard library.
"""

from __future__ import annotations

import html
import base64
import hmac
import json
import os
import shutil
import tempfile
import time
import urllib.parse
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .copilot import ask_copilot, precompute_copilot
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

# The mark: full vectorized SVG lockup from brand/logo.svg (emblem + मिलान)
_MARK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="7.40 3.90 765.77 222.59" height="38" class="brand-logo-svg" fill="#047857" role="img" aria-label="मिलान">'
    '<g fill-rule="evenodd">'
    '<path d="M0 0 C1.4 -0 2.8 -0.01 4.2 -0.02 C7.98 -0.03 11.76 -0.03 15.55 -0.03 C18.71 -0.03 21.88 -0.03 25.05 -0.04 C32.53 -0.05 40.01 -0.05 47.49 -0.04 C55.18 -0.03 62.87 -0.05 70.56 -0.07 C77.19 -0.09 83.82 -0.09 90.45 -0.09 C94.39 -0.09 98.34 -0.09 102.29 -0.1 C106 -0.12 109.72 -0.11 113.44 -0.1 C114.79 -0.1 116.14 -0.1 117.5 -0.11 C133.06 -0.2 147.78 3.17 159.39 14.09 C172.86 28.89 173.56 44.85 173.45 63.85 C173.45 66.03 173.45 68.2 173.45 70.38 C173.45 74.92 173.44 79.46 173.42 84 C173.39 89.8 173.39 95.6 173.4 101.4 C173.41 105.89 173.4 110.38 173.39 114.87 C173.39 117 173.39 119.14 173.39 121.28 C173.39 124.27 173.38 127.27 173.35 130.26 C173.36 130.69 173.36 130.69 173.37 132.89 C173.21 146.4 167.28 157.39 158.22 167.17 C148.92 175.81 137.56 180.38 124.92 180.42 C124.34 180.42 123.75 180.42 123.14 180.42 C121.18 180.43 119.22 180.43 117.26 180.44 C115.85 180.44 114.44 180.45 113.03 180.45 C109.21 180.46 105.38 180.47 101.56 180.47 C99.16 180.48 96.77 180.48 94.38 180.49 C86.87 180.5 79.37 180.51 71.87 180.51 C63.23 180.52 54.59 180.54 45.96 180.56 C39.27 180.59 32.58 180.6 25.89 180.6 C21.9 180.6 17.91 180.6 13.92 180.62 C10.16 180.64 6.4 180.64 2.64 180.63 C1.27 180.63 -0.1 180.64 -1.47 180.65 C-18.18 180.76 -31.73 176.93 -44.05 165.27 C-53.04 154.77 -57.18 143.64 -57.23 130.01 C-57.23 129.08 -57.24 128.16 -57.25 127.2 C-57.27 124.14 -57.28 121.08 -57.29 118.02 C-57.29 116.98 -57.3 115.93 -57.3 114.84 C-57.32 109.29 -57.34 103.73 -57.35 98.17 C-57.36 92.45 -57.39 86.74 -57.43 81.02 C-57.46 76.61 -57.46 72.19 -57.47 67.78 C-57.47 65.67 -57.48 63.57 -57.5 61.46 C-57.65 43.35 -55.78 28.04 -43 14.12 C-30.73 2.47 -16.26 -0.03 0 0 Z M-27.05 30.27 C-35.87 42.26 -35.36 54.79 -35.35 69.06 C-35.35 70.88 -35.36 72.7 -35.36 74.52 C-35.37 78.33 -35.37 82.14 -35.37 85.94 C-35.36 90.8 -35.38 95.65 -35.4 100.51 C-35.41 104.27 -35.42 108.02 -35.41 111.78 C-35.41 113.57 -35.42 115.36 -35.43 117.15 C-35.49 129.57 -35.41 140.32 -27.08 150.29 C-19.53 157.65 -11.41 158.43 -1.37 158.37 C-0.91 158.37 -0.91 158.37 1.43 158.37 C4.37 158.36 7.32 158.35 10.26 158.34 C12.26 158.33 14.26 158.33 16.26 158.32 C21.16 158.31 26.05 158.3 30.95 158.27 C30.08 153.68 28.61 149.62 26.89 145.29 C24.88 138.84 24.8 132.21 24.79 125.51 C24.79 125.09 24.79 125.09 24.77 122.97 C24.76 120.23 24.75 117.48 24.75 114.74 C24.75 114.26 24.75 114.26 24.74 111.87 C24.72 106.86 24.71 101.85 24.71 96.84 C24.7 91.71 24.68 86.57 24.65 81.43 C24.63 77.45 24.63 73.47 24.63 69.48 C24.62 67.59 24.62 65.7 24.6 63.81 C24.51 49.41 25.15 36.32 31.95 23.27 C25.55 23.2 19.14 23.15 12.74 23.11 C10.56 23.09 8.38 23.07 6.21 23.05 C3.07 23.01 -0.07 22.99 -3.21 22.98 C-4.17 22.97 -5.14 22.95 -6.13 22.93 C-14.15 22.93 -21.27 24.35 -27.05 30.27 Z M84.95 23.27 C86.85 28.98 86.85 28.98 87.77 31.65 C88.01 32.37 88.26 33.09 88.51 33.84 C88.76 34.56 89.01 35.28 89.27 36.03 C90.94 41.53 91.1 46.67 91.11 52.37 C91.12 53.28 91.12 54.19 91.13 55.12 C91.14 58.12 91.15 61.12 91.15 64.12 C91.16 66.22 91.16 68.31 91.17 70.4 C91.18 74.8 91.19 79.19 91.19 83.58 C91.2 89.18 91.22 94.79 91.25 100.39 C91.27 104.72 91.27 109.05 91.27 113.37 C91.28 115.44 91.28 117.5 91.3 119.57 C91.38 132.61 91.43 144.56 84.95 156.27 C84.95 156.93 84.95 157.59 84.95 158.27 C90.77 158.35 96.58 158.4 102.4 158.44 C104.38 158.45 106.35 158.47 108.33 158.5 C111.18 158.54 114.03 158.55 116.88 158.57 C117.76 158.58 118.63 158.6 119.53 158.61 C129.17 158.62 136.85 155.84 143.95 149.27 C153.12 139.78 151.25 125.46 151.22 113.24 C151.22 111.39 151.22 109.54 151.22 107.7 C151.22 103.84 151.22 99.98 151.21 96.13 C151.2 91.2 151.21 86.28 151.22 81.35 C151.23 77.54 151.22 73.73 151.22 69.92 C151.22 68.11 151.22 66.29 151.22 64.48 C151.23 61.93 151.22 59.39 151.21 56.85 C151.21 56.11 151.22 55.37 151.22 54.61 C151.15 45.41 149.49 37.86 142.9 31.2 C135.2 23.99 129.81 22.97 119.52 23.08 C118.53 23.08 117.54 23.09 116.52 23.09 C113.37 23.1 110.22 23.12 107.07 23.15 C104.93 23.16 102.79 23.17 100.65 23.18 C95.42 23.2 90.18 23.23 84.95 23.27 Z " transform="translate(69.050048828125, 41.725341796875)"/>'
    '<path d="M0 0 C1.31 0.75 2.62 1.47 3.95 2.19 C9.43 5.16 14.55 8.44 19.64 12.04 C20.01 12.3 20.01 12.3 21.87 13.58 C25.87 16.4 29.01 19.03 31.82 23.04 C29.51 26.34 27.2 29.64 24.82 33.04 C20.73 32.22 19.21 31.92 16 29.82 C15.29 29.37 14.58 28.92 13.85 28.45 C13.1 27.96 12.35 27.48 11.57 26.98 C-10.14 13.42 -36.6 2.33 -62.68 8.29 C-69.62 10.27 -73.98 12.99 -78.18 19.04 C-79.18 22.06 -79.34 24.2 -79.36 27.35 C-79.38 28.28 -79.39 29.2 -79.41 30.16 C-79.18 33.04 -79.18 33.04 -77.18 39.04 C68.02 39.37 213.22 39.7 362.82 40.04 C370.99 56.38 370.99 56.38 369.82 61.04 C362.89 61.04 355.96 61.04 348.82 61.04 C348.82 98 348.82 134.96 348.82 173.04 C348.16 173.37 347.5 173.7 346.82 174.04 C338.9 170.41 330.98 166.78 322.82 163.04 C322.82 145.88 322.82 128.72 322.82 111.04 C312.59 110.71 302.36 110.38 291.82 110.04 C292.01 118.73 292.01 118.73 292.09 121.44 C292.14 126.1 291.98 129.33 288.82 133.04 C285.59 135.04 282.26 135.36 278.58 134.55 C268.22 130.51 262.58 122.2 258.18 112.45 C255.87 106.91 255 102.48 256.95 96.73 C260.63 91.45 264.09 89.71 270.19 88.44 C275 87.71 279.79 87.8 284.64 87.85 C285.74 87.85 286.84 87.85 287.97 87.86 C290.85 87.86 293.74 87.88 296.62 87.91 C299.58 87.93 302.53 87.93 305.49 87.94 C311.27 87.97 317.05 88 322.82 88.04 C322.82 79.13 322.82 70.22 322.82 61.04 C295.43 61.04 268.04 61.04 239.82 61.04 C240.15 98 240.48 134.96 240.82 173.04 C237.38 174.19 236.96 173.95 233.8 172.53 C233.03 172.18 232.25 171.84 231.46 171.48 C230.65 171.11 229.84 170.74 229.01 170.35 C228.22 170 227.42 169.65 226.6 169.29 C221.93 167.17 218.19 164.95 213.82 162.04 C214.15 128.71 214.48 95.38 214.82 61.04 C207.89 61.04 200.96 61.04 193.82 61.04 C193.79 72.02 193.77 83 193.76 93.98 C193.76 94.79 193.76 95.6 193.76 96.43 C193.74 121.98 193.94 147.5 194.82 173.04 C190.98 174.32 190.11 173.51 186.54 171.77 C185.51 171.27 184.49 170.78 183.43 170.27 C182.36 169.74 181.28 169.2 180.2 168.67 C179.11 168.14 178.03 167.61 176.94 167.09 C169 163.22 169 163.22 167.82 162.04 C167.73 160.2 167.71 158.36 167.71 156.51 C167.71 155.94 167.71 155.36 167.71 154.77 C167.71 152.86 167.72 150.95 167.73 149.04 C167.73 147.72 167.73 146.4 167.73 145.07 C167.73 141.59 167.74 138.11 167.76 134.62 C167.77 131.07 167.77 127.52 167.78 123.97 C167.79 116.99 167.8 110.02 167.82 103.04 C163.31 99.49 159.55 98.77 153.82 99.04 C149.7 100.28 147.59 103.02 145.51 106.67 C141.3 116.28 143.21 126.06 144.82 136.04 C141.37 137.22 139.17 136.84 135.69 135.86 C134.72 135.59 133.75 135.32 132.75 135.05 C131.74 134.76 130.74 134.47 129.7 134.17 C128.68 133.89 127.67 133.6 126.63 133.31 C119.18 131.22 119.18 131.22 116.82 130.04 C116.8 127.04 116.78 124.04 116.76 121.04 C116.75 120.2 116.75 119.36 116.74 118.5 C116.72 113.25 117.06 108.24 117.82 103.04 C112.79 99.98 108.96 98.29 103 99.3 C98.27 100.91 94.97 104.11 92.45 108.35 C89.99 118.94 91.05 127.88 96.22 137.54 C102.3 147.04 111.98 156.48 121.82 162.04 C120.29 165.72 118.04 168.03 115.2 170.79 C114.79 171.19 114.79 171.19 112.72 173.21 C112.1 173.82 111.47 174.42 110.82 175.04 C106.21 173.75 103.29 172.13 99.57 168.98 C99.1 168.58 98.63 168.18 98.15 167.77 C97.18 166.94 96.21 166.11 95.24 165.27 C93.91 164.11 92.56 162.97 91.21 161.84 C78.6 150.94 66.54 136.17 64.6 119.03 C63.78 107.75 64.73 97.58 72.26 88.6 C73.43 87.4 74.61 86.21 75.82 85.04 C76.59 84.3 77.35 83.56 78.14 82.79 C87.77 76.52 97.59 75.77 108.82 77.04 C115.32 78.54 120.03 81.5 124.82 86.04 C129.03 85.29 131.4 83.17 134.63 80.52 C139.5 77.25 144.44 76.66 150.14 76.67 C150.79 76.67 151.45 76.67 152.12 76.67 C157.7 76.79 162.02 78.19 166.82 81.04 C167.48 81.37 168.14 81.7 168.82 82.04 C168.82 75.11 168.82 68.18 168.82 61.04 C153.56 61.02 138.3 61 123.03 60.99 C115.94 60.99 108.86 60.98 101.77 60.97 C95.59 60.96 89.41 60.95 83.23 60.95 C79.96 60.95 76.69 60.94 73.42 60.94 C69.76 60.93 66.11 60.93 62.45 60.93 C61.91 60.93 61.91 60.93 59.18 60.92 C58.18 60.92 57.18 60.92 56.15 60.92 C55.28 60.92 54.42 60.92 53.53 60.92 C50.28 61.07 47.05 61.58 43.82 62.04 C43.82 99 43.82 135.96 43.82 174.04 C39.98 172.76 36.51 171.54 32.86 169.88 C32.07 169.52 31.27 169.16 30.45 168.79 C29.46 168.33 28.47 167.88 27.45 167.42 C24.27 165.97 21.1 164.53 17.82 163.04 C17.82 148.85 17.82 134.66 17.82 120.04 C7.26 120.04 -3.3 120.04 -14.18 120.04 C-14.18 124.66 -14.18 129.28 -14.18 134.04 C-17.18 140.04 -17.18 140.04 -18.83 141.21 C-25.3 142.82 -30.34 140.99 -36.18 138.04 C-43.98 133.22 -51.03 123.61 -53.78 114.88 C-54.69 110.68 -54.72 107.36 -53.05 103.29 C-50.67 100.44 -48.65 99.34 -45.18 98.04 C-43.2 98.04 -41.22 98.04 -39.18 98.04 C-39.51 85.83 -39.84 73.62 -40.18 61.04 C-50.74 61.04 -61.3 61.04 -72.18 61.04 C-71.85 98.33 -71.52 135.62 -71.18 174.04 C-74.97 173.28 -77.55 172.58 -80.97 171.05 C-81.85 170.65 -82.72 170.26 -83.63 169.85 C-84.53 169.44 -85.43 169.03 -86.36 168.6 C-87.28 168.2 -88.19 167.79 -89.13 167.37 C-95.92 164.3 -95.92 164.3 -98.18 162.04 C-98.42 160.22 -98.42 160.22 -98.42 157.97 C-98.42 157.12 -98.42 156.26 -98.42 155.38 C-98.42 154.45 -98.41 153.51 -98.4 152.54 C-98.4 151.56 -98.4 150.57 -98.4 149.56 C-98.4 146.29 -98.39 143.02 -98.37 139.75 C-98.37 137.49 -98.36 135.23 -98.36 132.97 C-98.36 127.62 -98.34 122.27 -98.32 116.91 C-98.3 110.82 -98.29 104.73 -98.28 98.64 C-98.26 86.11 -98.22 73.57 -98.18 61.04 C-103.13 60.71 -108.08 60.38 -113.18 60.04 C-120.18 46.53 -120.18 46.53 -120.18 40.04 C-113.25 40.04 -106.32 40.04 -99.18 40.04 C-100 37.88 -100.83 35.71 -101.68 33.48 C-104.88 24.29 -106.28 14.33 -102.55 5.04 C-97.47 -4.42 -89.96 -10.23 -79.71 -13.33 C-52.4 -20.06 -24.02 -13.89 0 0 Z M-16.18 61.04 C-16.02 62.05 -15.87 63.06 -15.71 64.1 C-14.88 70.72 -14.81 77.39 -14.61 84.04 C-14.47 88.66 -14.32 93.28 -14.18 98.04 C-3.62 98.04 6.94 98.04 17.82 98.04 C17.82 85.83 17.82 73.62 17.82 61.04 C13.46 60.42 9.8 59.92 5.5 59.91 C4.56 59.91 3.61 59.91 2.63 59.91 C2.15 59.91 2.15 59.91 -0.3 59.92 C-1.28 59.91 -2.25 59.91 -3.26 59.91 C-4.2 59.91 -5.15 59.91 -6.12 59.91 C-6.55 59.91 -6.55 59.91 -8.7 59.91 C-11.27 60.05 -13.66 60.48 -16.18 61.04 Z " transform="translate(398.175537109375, 27.95751953125)"/>'
    '</g>'
    '</svg>'
)

# Vectorized emblem on a high-contrast filled tile for browser tab favicon (32x32)
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#047857"/>'
    '<g fill="#FFFFFF" fill-rule="evenodd" transform="translate(2.82, 2.19) scale(0.1038)">'
    '<path d="M0 0 C1.4 -0 2.8 -0.01 4.2 -0.02 C7.98 -0.03 11.76 -0.03 15.55 -0.03 C18.71 -0.03 21.88 -0.03 25.05 -0.04 C32.53 -0.05 40.01 -0.05 47.49 -0.04 C55.18 -0.03 62.87 -0.05 70.56 -0.07 C77.19 -0.09 83.82 -0.09 90.45 -0.09 C94.39 -0.09 98.34 -0.09 102.29 -0.1 C106 -0.12 109.72 -0.11 113.44 -0.1 C114.79 -0.1 116.14 -0.1 117.5 -0.11 C133.06 -0.2 147.78 3.17 159.39 14.09 C172.86 28.89 173.56 44.85 173.45 63.85 C173.45 66.03 173.45 68.2 173.45 70.38 C173.45 74.92 173.44 79.46 173.42 84 C173.39 89.8 173.39 95.6 173.4 101.4 C173.41 105.89 173.4 110.38 173.39 114.87 C173.39 117 173.39 119.14 173.39 121.28 C173.39 124.27 173.38 127.27 173.35 130.26 C173.36 130.69 173.36 130.69 173.37 132.89 C173.21 146.4 167.28 157.39 158.22 167.17 C148.92 175.81 137.56 180.38 124.92 180.42 C124.34 180.42 123.75 180.42 123.14 180.42 C121.18 180.43 119.22 180.43 117.26 180.44 C115.85 180.44 114.44 180.45 113.03 180.45 C109.21 180.46 105.38 180.47 101.56 180.47 C99.16 180.48 96.77 180.48 94.38 180.49 C86.87 180.5 79.37 180.51 71.87 180.51 C63.23 180.52 54.59 180.54 45.96 180.56 C39.27 180.59 32.58 180.6 25.89 180.6 C21.9 180.6 17.91 180.6 13.92 180.62 C10.16 180.64 6.4 180.64 2.64 180.63 C1.27 180.63 -0.1 180.64 -1.47 180.65 C-18.18 180.76 -31.73 176.93 -44.05 165.27 C-53.04 154.77 -57.18 143.64 -57.23 130.01 C-57.23 129.08 -57.24 128.16 -57.25 127.2 C-57.27 124.14 -57.28 121.08 -57.29 118.02 C-57.29 116.98 -57.3 115.93 -57.3 114.84 C-57.32 109.29 -57.34 103.73 -57.35 98.17 C-57.36 92.45 -57.39 86.74 -57.43 81.02 C-57.46 76.61 -57.46 72.19 -57.47 67.78 C-57.47 65.67 -57.48 63.57 -57.5 61.46 C-57.65 43.35 -55.78 28.04 -43 14.12 C-30.73 2.47 -16.26 -0.03 0 0 Z M-27.05 30.27 C-35.87 42.26 -35.36 54.79 -35.35 69.06 C-35.35 70.88 -35.36 72.7 -35.36 74.52 C-35.37 78.33 -35.37 82.14 -35.37 85.94 C-35.36 90.8 -35.38 95.65 -35.4 100.51 C-35.41 104.27 -35.42 108.02 -35.41 111.78 C-35.41 113.57 -35.42 115.36 -35.43 117.15 C-35.49 129.57 -35.41 140.32 -27.08 150.29 C-19.53 157.65 -11.41 158.43 -1.37 158.37 C-0.91 158.37 -0.91 158.37 1.43 158.37 C4.37 158.36 7.32 158.35 10.26 158.34 C12.26 158.33 14.26 158.33 16.26 158.32 C21.16 158.31 26.05 158.3 30.95 158.27 C30.08 153.68 28.61 149.62 26.89 145.29 C24.88 138.84 24.8 132.21 24.79 125.51 C24.79 125.09 24.79 125.09 24.77 122.97 C24.76 120.23 24.75 117.48 24.75 114.74 C24.75 114.26 24.75 114.26 24.74 111.87 C24.72 106.86 24.71 101.85 24.71 96.84 C24.7 91.71 24.68 86.57 24.65 81.43 C24.63 77.45 24.63 73.47 24.63 69.48 C24.62 67.59 24.62 65.7 24.6 63.81 C24.51 49.41 25.15 36.32 31.95 23.27 C25.55 23.2 19.14 23.15 12.74 23.11 C10.56 23.09 8.38 23.07 6.21 23.05 C3.07 23.01 -0.07 22.99 -3.21 22.98 C-4.17 22.97 -5.14 22.95 -6.13 22.93 C-14.15 22.93 -21.27 24.35 -27.05 30.27 Z M84.95 23.27 C86.85 28.98 86.85 28.98 87.77 31.65 C88.01 32.37 88.26 33.09 88.51 33.84 C88.76 34.56 89.01 35.28 89.27 36.03 C90.94 41.53 91.1 46.67 91.11 52.37 C91.12 53.28 91.12 54.19 91.13 55.12 C91.14 58.12 91.15 61.12 91.15 64.12 C91.16 66.22 91.16 68.31 91.17 70.4 C91.18 74.8 91.19 79.19 91.19 83.58 C91.2 89.18 91.22 94.79 91.25 100.39 C91.27 104.72 91.27 109.05 91.27 113.37 C91.28 115.44 91.28 117.5 91.3 119.57 C91.38 132.61 91.43 144.56 84.95 156.27 C84.95 156.93 84.95 157.59 84.95 158.27 C90.77 158.35 96.58 158.4 102.4 158.44 C104.38 158.45 106.35 158.47 108.33 158.5 C111.18 158.54 114.03 158.55 116.88 158.57 C117.76 158.58 118.63 158.6 119.53 158.61 C129.17 158.62 136.85 155.84 143.95 149.27 C153.12 139.78 151.25 125.46 151.22 113.24 C151.22 111.39 151.22 109.54 151.22 107.7 C151.22 103.84 151.22 99.98 151.21 96.13 C151.2 91.2 151.21 86.28 151.22 81.35 C151.23 77.54 151.22 73.73 151.22 69.92 C151.22 68.11 151.22 66.29 151.22 64.48 C151.23 61.93 151.22 59.39 151.21 56.85 C151.21 56.11 151.22 55.37 151.22 54.61 C151.15 45.41 149.49 37.86 142.9 31.2 C135.2 23.99 129.81 22.97 119.52 23.08 C118.53 23.08 117.54 23.09 116.52 23.09 C113.37 23.1 110.22 23.12 107.07 23.15 C104.93 23.16 102.79 23.17 100.65 23.18 C95.42 23.2 90.18 23.23 84.95 23.27 Z " transform="translate(69.050048828125, 41.725341796875)"/>'
    '</g>'
    '</svg>'
)

# Vercel caps a serverless request body at 4.5 MB and rejects anything larger
# at the platform edge -- before this process runs, so our own error page would
# never be shown. Refusing just under it means the practitioner gets a readable
# message instead of an opaque platform 413.
MAX_UPLOAD = 4 * 1024 * 1024

# Set MILAN_PASSWORD in the deployment environment to require a shared password.
# Left unset (local use) the app is open, which is correct when it is bound to
# 127.0.0.1 and wrong the moment it has a public URL. This handles a real
# client's GSTINs, supplier list and complete tax position.
_PASSWORD = os.environ.get("MILAN_PASSWORD", "").strip()
_RESULTS: dict[str, dict] = {}
_SWAP_SESSIONS: dict[str, dict] = {}
_TMP = Path(tempfile.gettempdir()) / "milan_sessions"
_TMP.mkdir(parents=True, exist_ok=True)


def _cleanup_old_sessions(max_age_seconds: int = 7200, max_sessions: int = 50) -> None:
    """Evict expired sessions and delete temporary files to keep production disk clean."""
    now = time.time()
    expired = [
        t for t, d in _RESULTS.items()
        if now - d.get("created_at", now) > max_age_seconds
    ]
    for t in expired:
        d = _RESULTS.pop(t, None)
        if d and "folder" in d:
            shutil.rmtree(d["folder"], ignore_errors=True)
    if len(_RESULTS) > max_sessions:
        sorted_tokens = sorted(_RESULTS.keys(), key=lambda t: _RESULTS[t].get("created_at", 0))
        for t in sorted_tokens[:len(_RESULTS) - max_sessions]:
            d = _RESULTS.pop(t, None)
            if d and "folder" in d:
                shutil.rmtree(d["folder"], ignore_errors=True)


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;0,6..72,700;1,6..72,400&family=JetBrains+Mono:wght@400;500;600&family=Noto+Serif+Devanagari:wght@600;700;800&family=Noto+Sans+Devanagari:wght@600;700;800&family=Rozha+One&display=swap');

:root {
  /* Solid Clean Backgrounds */
  --bg: #F8FAFC;
  --bg-subtle: #F1F5F9;
  --card-bg: #FFFFFF;
  --card-hover: #FAFAFA;

  /* Solid Crisp Borders */
  --border: #E2E8F0;
  --border-strong: #CBD5E1;
  --border-focus: #0F172A;

  /* Primary Institutional Palette */
  --navy: #0F172A;
  --navy-dark: #020617;
  --slate-dark: #1E293B;
  --slate-mid: #334155;
  --text-primary: #0F172A;
  --text-secondary: #475569;
  --text-muted: #64748B;
  --text-light: #94A3B8;

  /* Milan Brand Colors (Emerald Core) */
  --brand-emerald: #047857;
  --brand-emerald-vibrant: #059669;
  --brand-emerald-light: #10B981;
  --brand-emerald-soft: #ECFDF5;
  --brand-emerald-border: #A7F3D0;
  
  /* Trust Emerald */
  --trust-emerald: #059669;
  --trust-emerald-bg: #ECFDF5;
  --trust-emerald-border: #A7F3D0;
  --trust-emerald-hover: #047857;

  /* Alert Crimson */
  --alert-crimson: #DC2626;
  --alert-crimson-bg: #FEF2F2;
  --alert-crimson-border: #FECACA;

  /* Warning Amber */
  --warning-amber: #D97706;
  --warning-amber-bg: #FFFBEB;
  --warning-amber-border: #FDE68A;

  /* Accent Indigo */
  --accent-indigo: #4F46E5;
  --accent-indigo-bg: #EEF2FF;
  --accent-indigo-border: #C7D2FE;

  /* Government Portal Sapphire Blue */
  --accent-blue: #2563EB;
  --accent-blue-dark: #1D4ED8;
  --accent-blue-bg: #EFF6FF;
  --accent-blue-border: #BFDBFE;

  /* Statutory Return Royal Purple */
  --accent-purple: #7C3AED;
  --accent-purple-dark: #6D28D9;
  --accent-purple-bg: #F5F3FF;
  --accent-purple-border: #DDD6FE;

  /* Geometry & Subtle Elevations */
  --radius-xs: 4px;
  --radius-sm: 6px;
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-card: 0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03);
  --shadow-card-hover: 0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.05);

  /* Typography */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-serif: 'Newsreader', 'Merriweather', Georgia, serif;
  --font-mono: 'JetBrains Mono', SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --font-deva: 'Noto Serif Devanagari', 'Rozha One', 'Noto Sans Devanagari', 'Mangal', 'Nirmala UI', serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg);
  color: var(--navy);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
}
body::before {
  content: "";
  display: block;
  height: 3.5px;
  background: linear-gradient(90deg, #059669 0%, #2563EB 50%, #7C3AED 100%);
  width: 100%;
  position: fixed;
  top: 0;
  left: 0;
  z-index: 99999;
}

.wrap {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px 80px;
}

/* Typography Hierarchy */
h1, h2, h3, .serif-title {
  font-family: var(--font-serif);
  font-weight: 600;
  color: var(--navy);
  letter-spacing: -0.015em;
}
.hero-title {
  font-family: var(--font-serif);
  font-size: 32px;
  font-weight: 700;
  color: var(--navy);
  line-height: 1.25;
  margin-bottom: 8px;
}
.hero-sub {
  font-size: 15px;
  color: var(--text-secondary);
  max-width: 760px;
  line-height: 1.55;
  margin-bottom: 24px;
}

/* Header & Institutional Navigation */
.brand-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  gap: 16px;
}
.brand-lockup {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  user-select: none;
  transition: opacity 0.15s ease;
}
.brand-lockup:hover {
  opacity: 0.88;
}
.brand-logo-svg {
  display: block;
  height: 38px;
  width: auto;
  flex-shrink: 0;
}
.brand-wordmark {
  font-family: var(--font-deva);
  font-size: 34px;
  font-weight: 700;
  color: var(--navy);
  line-height: 1;
  letter-spacing: 0.01em;
  display: inline-flex;
  align-items: center;
}
.brand-sep {
  color: var(--border-strong);
  font-size: 20px;
  font-weight: 300;
  margin: 0 4px;
}
.brand-stats {
  font-family: var(--font-sans);
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}
.header-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}
.badge-ca-desk {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-blue-dark);
  background: var(--accent-blue-bg);
  border: 1px solid var(--accent-blue-border);
  padding: 6px 12px;
  border-radius: var(--radius-xs);
}
.badge-status-secure {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: var(--trust-emerald-bg);
  border: 1px solid var(--trust-emerald-border);
  color: var(--trust-emerald);
  padding: 6px 12px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
}
.status-dot {
  width: 7px;
  height: 7px;
  background-color: var(--trust-emerald);
  border-radius: 50%;
  display: inline-block;
  box-shadow: 0 0 0 2.5px rgba(5, 150, 105, 0.25);
}

/* Tabs Navigation */
.tabs-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 24px;
  overflow-x: auto;
}
.tab-btn {
  background: none;
  border: none;
  padding: 12px 18px;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: color 0.15s ease, border-color 0.15s ease;
  white-space: nowrap;
}
.tab-btn:hover {
  color: var(--brand-emerald-vibrant);
}
.tab-btn.active {
  color: var(--brand-emerald-vibrant);
  border-bottom-color: var(--brand-emerald-vibrant);
  font-weight: 700;
}
.tab-btn:nth-child(2).active {
  color: var(--accent-indigo);
  border-bottom-color: var(--accent-indigo);
}
.tab-btn:nth-child(3).active {
  color: var(--warning-amber);
  border-bottom-color: var(--warning-amber);
}
.tab-btn:nth-child(4).active {
  color: var(--accent-purple);
  border-bottom-color: var(--accent-purple);
}
.tab-pane {
  display: none;
}
.tab-pane.active {
  display: block;
  animation: fadeIn 0.2s ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Bento Grid Architecture */
.bento-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 18px;
  margin-bottom: 22px;
}
.bento-col-4 { grid-column: span 4; }
.bento-col-6 { grid-column: span 6; }
.bento-col-8 { grid-column: span 8; }
.bento-col-12 { grid-column: span 12; }

/* Solid Modular Cards */
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 24px 26px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-card);
}
.card-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 12px;
}
.card-title {
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 600;
  color: var(--navy);
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 16px;
  line-height: 1.45;
}

/* Metric Cards */
.metric-grid-4 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 22px;
}
.metric-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 22px;
}
.metric-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 18px 20px;
  box-shadow: var(--shadow-card);
}
.metric-card.accent {
  border-top: 3px solid var(--trust-emerald);
}
.metric-card.alert {
  border-top: 3px solid var(--warning-amber);
}
.metric-card.danger {
  border-top: 3px solid var(--alert-crimson);
}
.metric-card.indigo {
  border-top: 3px solid var(--accent-indigo);
}
.metric-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.metric-val {
  font-family: var(--font-mono);
  font-size: 24px;
  font-weight: 700;
  color: var(--navy);
  letter-spacing: -0.02em;
}
.metric-card.accent .metric-val { color: var(--trust-emerald); }
.metric-card.alert .metric-val { color: var(--warning-amber); }
.metric-card.danger .metric-val { color: var(--alert-crimson); }
.metric-card.indigo .metric-val { color: var(--accent-indigo); }
.metric-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* Circular Donut Chart (Accuracy Visualization) */
.donut-box {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 0 6px;
}
.donut-svg-wrap {
  position: relative;
  width: 96px;
  height: 96px;
  flex-shrink: 0;
}
.donut-svg {
  transform: rotate(-90deg);
  width: 96px;
  height: 96px;
}
.donut-center-text {
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.donut-pct {
  font-family: var(--font-mono);
  font-size: 19px;
  font-weight: 700;
  color: var(--navy);
  line-height: 1;
}
.donut-sub {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-top: 4px;
  letter-spacing: 0.05em;
}
.donut-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* High-Density Data Tables */
table {
  width: 100%;
  border-collapse: collapse;
}
th {
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border-strong);
  padding: 11px 14px;
  text-align: left;
}
td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--navy);
  vertical-align: middle;
}
tr:hover td {
  background: #F8FAFC;
}
td.n {
  text-align: right;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  white-space: nowrap;
}
.tbl-strong {
  font-weight: 600;
  color: var(--navy);
}
.delta-pos { color: var(--trust-emerald); font-weight: 700; }
.delta-neg { color: var(--alert-crimson); font-weight: 700; }

/* Status Pills & Badges */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  white-space: nowrap;
}
.status-pill.claim {
  background: var(--trust-emerald-bg);
  color: var(--trust-emerald);
  border: 1px solid var(--trust-emerald-border);
}
.status-pill.reverse {
  background: var(--alert-crimson-bg);
  color: var(--alert-crimson);
  border: 1px solid var(--alert-crimson-border);
}
.status-pill.review {
  background: var(--warning-amber-bg);
  color: var(--warning-amber);
  border: 1px solid var(--warning-amber-border);
}

.grade-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: var(--radius-xs);
  text-align: center;
}
.grade-A { background: var(--trust-emerald-bg); color: var(--trust-emerald); border: 1px solid var(--trust-emerald-border); }
.grade-B { background: var(--warning-amber-bg); color: var(--warning-amber); border: 1px solid var(--warning-amber-border); }
.grade-C { background: var(--alert-crimson-bg); color: var(--alert-crimson); border: 1px solid var(--alert-crimson-border); }
.grade-D { background: var(--bg-subtle); color: var(--slate-mid); border: 1px solid var(--border-strong); }

.ims-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: var(--radius-xs);
}
.ims-accept { background: var(--trust-emerald-bg); color: var(--trust-emerald); border: 1px solid var(--trust-emerald-border); }
.ims-pending { background: var(--warning-amber-bg); color: var(--warning-amber); border: 1px solid var(--warning-amber-border); }
.ims-reject { background: var(--alert-crimson-bg); color: var(--alert-crimson); border: 1px solid var(--alert-crimson-border); }
.ims-fix { background: var(--accent-indigo-bg); color: var(--accent-indigo); border: 1px solid var(--accent-indigo-border); }

/* Statutory Banners */
.highlight-banner {
  background: var(--alert-crimson-bg);
  border: 1px solid var(--alert-crimson-border);
  border-radius: var(--radius-sm);
  padding: 18px 22px;
  margin-bottom: 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}
.highlight-banner.blue {
  background: var(--accent-indigo-bg);
  border-color: var(--accent-indigo-border);
}
.hb-tag {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--alert-crimson);
  letter-spacing: 0.06em;
}
.highlight-banner.blue .hb-tag { color: var(--accent-indigo); }
.hb-title {
  font-family: var(--font-mono);
  font-size: 24px;
  font-weight: 700;
  color: var(--alert-crimson);
  letter-spacing: -0.02em;
  margin: 2px 0 4px;
}
.highlight-banner.blue .hb-title { color: var(--accent-indigo); }
.hb-desc {
  font-size: 13px;
  color: var(--text-secondary);
}
.hb-badge {
  background: var(--card-bg);
  padding: 8px 14px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--alert-crimson-border);
  font-size: 12px;
  font-weight: 600;
  color: var(--alert-crimson);
  text-align: right;
}
.highlight-banner.blue .hb-badge { border-color: var(--accent-indigo-border); color: var(--accent-indigo); }

/* Table 8 Waterfall Progress Flow */
.flow-chain {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 18px 0;
}
.flow-step {
  flex: 1;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  text-align: center;
  box-shadow: var(--shadow-sm);
}
.flow-step.active {
  border: 1px solid var(--trust-emerald);
  background: var(--trust-emerald-bg);
}
.flow-step-label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; }
.flow-step-val { font-family: var(--font-mono); font-size: 16px; font-weight: 700; color: var(--navy); margin-top: 4px; }
.flow-step.active .flow-step-val { color: var(--trust-emerald); }
.flow-arrow { color: var(--text-muted); font-size: 16px; font-weight: 700; }

/* Drafter & Preformatted code */
pre.code-draft {
  background: var(--bg-subtle);
  color: var(--navy);
  padding: 16px 18px;
  border-radius: var(--radius-xs);
  font-family: var(--font-mono);
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
  background: var(--trust-emerald-bg);
  color: var(--trust-emerald);
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--trust-emerald-border);
}
.btn-copy {
  background: var(--card-bg);
  border: 1px solid var(--border-strong);
  color: var(--navy);
  padding: 5px 12px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-copy:hover {
  background: var(--bg-subtle);
}

/* Drag-and-Drop Upload Zone */
.upload-error-banner {
  background: #FEF2F2;
  border: 1px solid #FECACA;
  border-left: 4px solid #DC2626;
  border-radius: var(--radius-sm);
  padding: 14px 18px;
  margin-bottom: 20px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  box-shadow: var(--shadow-sm);
  animation: fadeIn 0.2s ease-out;
}
.err-icon {
  color: #DC2626;
  flex-shrink: 0;
  margin-top: 1px;
}
.err-content {
  flex: 1;
}
.err-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #991B1B;
  margin-bottom: 2px;
}
.err-msg {
  font-size: 13px;
  color: #7F1D1D;
  line-height: 1.45;
}
.err-close {
  background: none;
  border: none;
  color: #991B1B;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.err-close:hover {
  color: #DC2626;
}

.upload-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
  margin: 20px 0 24px;
}
.dropzone {
  position: relative;
  border-radius: var(--radius-sm);
  padding: 24px 20px;
  text-align: center;
  background: var(--card-bg);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  user-select: none;
}
.dropzone input.dz-hidden-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
  z-index: -1;
}

/* Empty vs Attached State Switching */
.dropzone .dz-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  pointer-events: none;
}
.dropzone .dz-attached-state {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
}
.dropzone.has-file .dz-empty-state {
  display: none !important;
}
.dropzone.has-file .dz-attached-state {
  display: flex !important;
}

/* Base Empty State Elements */
.dz-icon {
  width: 46px;
  height: 46px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  transition: transform 0.15s ease;
}
.dropzone:hover .dz-icon {
  transform: scale(1.08);
}
.dz-pill {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  margin-bottom: 8px;
}
.dz-title {
  font-family: var(--font-sans);
  font-weight: 700;
  font-size: 14.5px;
  color: var(--navy);
  margin-bottom: 4px;
}
.dz-sub {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}
.dz-action-hint {
  margin-top: 12px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-muted);
  background: rgba(0, 0, 0, 0.03);
  padding: 5px 12px;
  border-radius: var(--radius-xs);
  border: 1px dashed var(--border);
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.dropzone:hover .dz-action-hint {
  border-color: currentColor;
  color: var(--navy);
  background: rgba(255, 255, 255, 0.9);
}

/* Attached State Elements */
.dz-attached-check {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.dz-pill-attached {
  display: inline-block;
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  margin-bottom: 6px;
  color: #FFFFFF;
}
.dz-attached-doc-type {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}
.dz-file-card {
  width: 100%;
  max-width: 320px;
  background: #FFFFFF;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  padding: 10px 14px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
  margin-bottom: 12px;
  text-align: left;
}
.dz-file-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dz-file-ext-icon {
  font-size: 9.5px;
  font-weight: 800;
  padding: 3px 6px;
  border-radius: 3px;
  font-family: var(--font-mono);
  letter-spacing: 0.05em;
  flex-shrink: 0;
}
.dz-file-meta {
  flex: 1;
  min-width: 0;
}
.dz-file-title {
  display: block;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  color: var(--navy);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dz-file-size {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.dz-attached-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  max-width: 320px;
  font-size: 11.5px;
}
.dz-replace-text {
  color: var(--text-muted);
  font-size: 11px;
}
.dropzone:hover .dz-replace-text {
  color: var(--navy);
  text-decoration: underline;
}
.dz-btn-remove {
  background: #FEF2F2;
  border: 1px solid #FECACA;
  color: #DC2626;
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
  pointer-events: auto;
}
.dz-btn-remove:hover {
  background: #FEE2E2;
  border-color: #F87171;
  color: #B91C1C;
}

/* Dragover Hover Accents */
.dropzone.dragover {
  border-style: solid !important;
  transform: scale(1.02) !important;
  box-shadow: 0 12px 28px -5px rgba(0,0,0,0.15) !important;
}
.dropzone.dz-portal.dragover {
  border-color: #1D4ED8 !important;
  background: #DBEAFE !important;
}
.dropzone.dz-books.dragover {
  border-color: #059669 !important;
  background: #D1FAE5 !important;
}
.dropzone.dz-gstr3b.dragover {
  border-color: #7C3AED !important;
  background: #EDE9FE !important;
}

/* Specific Dropzone Themes (Empty & Attached) */
.dropzone.dz-portal {
  border: 2px dashed #93C5FD;
  background: linear-gradient(180deg, #F8FAFF 0%, #FFFFFF 100%);
}
.dropzone.dz-portal:hover {
  border-color: #2563EB;
  background: #EFF6FF;
  transform: translateY(-1px);
}
.dropzone.dz-portal.has-file {
  border: 2px solid #2563EB !important;
  background: linear-gradient(180deg, #EFF6FF 0%, #FFFFFF 100%) !important;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.12) !important;
}
.dropzone.dz-portal .dz-icon {
  background: #DBEAFE;
  color: #1D4ED8;
  border: 1px solid #BFDBFE;
}
.dropzone.dz-portal .dz-pill.req {
  background: #1D4ED8;
  color: #FFFFFF;
}
.dropzone.dz-portal .dz-attached-check {
  background: #EFF6FF;
  border: 2px solid #93C5FD;
}
.dropzone.dz-portal .dz-pill-attached { background: #2563EB; }
.dropzone.dz-portal .dz-file-card { border-color: #BFDBFE; }
.dropzone.dz-portal .dz-file-ext-icon { background: #DBEAFE; color: #1D4ED8; border: 1px solid #BFDBFE; }

.dropzone.dz-books {
  border: 2px dashed #86EFAC;
  background: linear-gradient(180deg, #F6FFF9 0%, #FFFFFF 100%);
}
.dropzone.dz-books:hover {
  border-color: #059669;
  background: #ECFDF5;
  transform: translateY(-1px);
}
.dropzone.dz-books.has-file {
  border: 2px solid #059669 !important;
  background: linear-gradient(180deg, #ECFDF5 0%, #FFFFFF 100%) !important;
  box-shadow: 0 4px 14px rgba(5, 150, 105, 0.12) !important;
}
.dropzone.dz-books .dz-icon {
  background: #D1FAE5;
  color: #047857;
  border: 1px solid #A7F3D0;
}
.dropzone.dz-books .dz-pill.req {
  background: #059669;
  color: #FFFFFF;
}
.dropzone.dz-books .dz-attached-check {
  background: #ECFDF5;
  border: 2px solid #86EFAC;
}
.dropzone.dz-books .dz-pill-attached { background: #059669; }
.dropzone.dz-books .dz-file-card { border-color: #A7F3D0; }
.dropzone.dz-books .dz-file-ext-icon { background: #D1FAE5; color: #047857; border: 1px solid #A7F3D0; }

.dropzone.dz-gstr3b {
  border: 2px dashed #C4B5FD;
  background: linear-gradient(180deg, #FAF8FF 0%, #FFFFFF 100%);
}
.dropzone.dz-gstr3b:hover {
  border-color: #7C3AED;
  background: #F5F3FF;
  transform: translateY(-1px);
}
.dropzone.dz-gstr3b.has-file {
  border: 2px solid #7C3AED !important;
  background: linear-gradient(180deg, #F5F3FF 0%, #FFFFFF 100%) !important;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.12) !important;
}
.dropzone.dz-gstr3b .dz-icon {
  background: #EDE9FE;
  color: #6D28D9;
  border: 1px solid #DDD6FE;
}
.dropzone.dz-gstr3b .dz-pill.opt {
  background: #7C3AED;
  color: #FFFFFF;
  border: none;
}
.dropzone.dz-gstr3b .dz-attached-check {
  background: #F5F3FF;
  border: 2px solid #C4B5FD;
}
.dropzone.dz-gstr3b .dz-pill-attached { background: #7C3AED; }
.dropzone.dz-gstr3b .dz-file-card { border-color: #DDD6FE; }
.dropzone.dz-gstr3b .dz-file-ext-icon { background: #EDE9FE; color: #6D28D9; border: 1px solid #DDD6FE; }

/* Interactive Table Filter */
.table-search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--card-bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  padding: 8px 14px;
  transition: border-color 0.15s ease;
}
.table-search-box:focus-within {
  border-color: var(--navy);
}
.table-search-box input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--navy);
  font-family: var(--font-sans);
  font-size: 13px;
  width: 100%;
}
.table-search-box input::placeholder {
  color: var(--text-muted);
}

/* Action Buttons */
button.btn-primary {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  color: #FFFFFF;
  border: 1px solid #047857;
  border-radius: var(--radius-sm);
  padding: 13px 28px;
  font-family: var(--font-sans);
  font-size: 14.5px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 4px 14px rgba(5, 150, 105, 0.28);
  transition: all 0.15s ease;
}
button.btn-primary:hover {
  background: linear-gradient(135deg, #10B981 0%, #059669 100%);
  box-shadow: 0 6px 18px rgba(5, 150, 105, 0.38);
  transform: translateY(-1px);
}

/* Action Footer & Downloads */
.action-card {
  background: linear-gradient(180deg, #F0FDF4 0%, #FFFFFF 60%);
  border: 1px solid #A7F3D0;
  border-left: 4px solid #059669;
  border-radius: var(--radius-sm);
  padding: 24px 28px;
  margin-top: 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--shadow-card);
  gap: 20px;
  flex-wrap: wrap;
}
.action-text h3 {
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 700;
  color: #065F46;
  margin-bottom: 4px;
}
.action-text p {
  font-size: 13px;
  color: var(--text-secondary);
}
.btn-download {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  color: #FFFFFF;
  text-decoration: none;
  font-weight: 700;
  font-size: 13.5px;
  padding: 11px 20px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #047857;
  box-shadow: 0 3px 10px rgba(5, 150, 105, 0.25);
  transition: all 0.15s ease;
}
.btn-download:hover {
  background: linear-gradient(135deg, #10B981 0%, #059669 100%);
  box-shadow: 0 5px 14px rgba(5, 150, 105, 0.35);
  transform: translateY(-1px);
}
.btn-download.alt {
  background: #FFFFFF;
  color: #047857;
  border: 1.5px solid #A7F3D0;
  margin-left: 8px;
  box-shadow: none;
}
.btn-download.alt:hover {
  background: #ECFDF5;
  border-color: #059669;
}

.nav-back { margin-top: 24px; text-align: center; }
.nav-back a { color: var(--navy); text-decoration: none; font-weight: 600; font-size: 13px; }
.nav-back a:hover { text-decoration: underline; }

.trust-footer {
  margin-top: 36px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

/* Micro-Animated Processing Loader */
#loader {
  display: none;
  position: fixed;
  top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(15, 23, 42, 0.65);
  z-index: 99999;
  align-items: center;
  justify-content: center;
}
.loader-modal {
  background: #FFFFFF;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 36px 36px 32px;
  max-width: 420px;
  width: 90%;
  text-align: center;
  box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.15);
}
.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border);
  border-top-color: var(--navy);
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
  margin: 0 auto 16px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.loader-steps {
  margin-top: 18px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.loader-step-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.loader-step-item.done {
  color: var(--trust-emerald);
  font-weight: 600;
}

/* Floating Co-Pilot AI Controller */
.copilot-trigger {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: var(--navy);
  color: #FFFFFF;
  border: 1px solid var(--navy-dark);
  border-radius: var(--radius-sm);
  padding: 10px 18px;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 9990;
  transition: background-color 0.15s ease;
}
.copilot-trigger:hover {
  background: var(--slate-dark);
}
.copilot-chat-panel {
  position: fixed;
  bottom: 80px;
  right: 24px;
  width: 420px;
  max-width: calc(100vw - 32px);
  height: 560px;
  background: var(--card-bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.15);
  display: none;
  flex-direction: column;
  z-index: 9995;
  overflow: hidden;
}
.copilot-header {
  background: var(--navy);
  color: #FFFFFF;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.copilot-header-title {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.copilot-header-sub {
  font-size: 11px;
  color: var(--text-light);
  margin-top: 1px;
}
.copilot-close {
  background: none;
  border: none;
  color: var(--text-light);
  font-size: 18px;
  cursor: pointer;
}
.copilot-close:hover { color: #FFFFFF; }
.copilot-body {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg);
}
.chat-msg {
  padding: 12px 14px;
  border-radius: var(--radius-xs);
  font-size: 13px;
  line-height: 1.5;
  max-width: 90%;
}
.chat-msg.copilot {
  background: #FFFFFF;
  border: 1px solid var(--border);
  color: var(--navy);
  align-self: flex-start;
}
.chat-msg.user {
  background: var(--navy);
  color: #FFFFFF;
  align-self: flex-end;
}
.prompt-chips-chat {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.prompt-chip-chat {
  background: var(--bg-subtle);
  border: 1px solid var(--border-strong);
  color: var(--navy);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.prompt-chip-chat:hover {
  background: var(--card-bg);
  border-color: var(--navy);
}
.copilot-footer {
  padding: 12px;
  background: #FFFFFF;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
}
.copilot-input-field {
  flex: 1;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  padding: 8px 12px;
  font-family: var(--font-sans);
  font-size: 13px;
  outline: none;
  color: var(--navy);
}
.copilot-input-field:focus { border-color: var(--navy); }
.copilot-send-btn {
  background: var(--navy);
  color: #FFFFFF;
  border: none;
  border-radius: var(--radius-xs);
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

/* Toast */
#toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%) translateY(40px);
  background: var(--navy);
  color: #FFFFFF;
  padding: 10px 20px;
  border-radius: var(--radius-xs);
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
  opacity: 0;
  transition: all 0.2s ease;
  z-index: 99999;
}
#toast.show {
  transform: translateX(-50%) translateY(0);
  opacity: 1;
}

/* About Milan Pillars */
.about-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 28px;
}
.about-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
.about-card-title {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 700;
  color: var(--navy);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.about-card-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.about-card-desc code {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-subtle);
  padding: 1px 4px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border);
  color: var(--navy);
}

/* Purchase Register Export Guides (Scroll Down) */
.guide-section {
  margin-top: 40px;
  padding-top: 32px;
  border-top: 1px solid var(--border);
}
.guide-header {
  margin-bottom: 20px;
}
.guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 20px;
}
.guide-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 22px 24px;
  box-shadow: var(--shadow-sm);
}
.guide-card.tally {
  border: 1px solid #FDE68A;
  border-top: 4px solid #D97706;
}
.guide-card.tally .guide-badge {
  background: #FFFBEB;
  color: #B45309;
  border: 1px solid #FDE68A;
}
.guide-card.tally .guide-step-num {
  background: #EEF2FF;
  color: #4338CA;
  border: 1px solid #C7D2FE;
}

.guide-card.busy {
  border: 1px solid #BFDBFE;
  border-top: 4px solid #2563EB;
}
.guide-card.busy .guide-badge {
  background: #EFF6FF;
  color: #1D4ED8;
  border: 1px solid #BFDBFE;
}
.guide-card.busy .guide-step-num {
  background: #EFF6FF;
  color: #1D4ED8;
  border: 1px solid #BFDBFE;
}

.guide-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.guide-app-title {
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 700;
  color: var(--navy);
  display: flex;
  align-items: center;
  gap: 9px;
}
.guide-badge {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
  color: var(--navy);
  border: 1px solid var(--border-strong);
}
.guide-steps {
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.guide-step-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.guide-step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-subtle);
  border: 1px solid var(--border-strong);
  color: var(--navy);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.guide-note {
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  border-left: 4px solid #059669;
  border-radius: var(--radius-xs);
  padding: 14px 18px;
  font-size: 13px;
  color: #065F46;
  line-height: 1.55;
}
.guide-note strong {
  color: #047857;
}
.kbd {
  display: inline-block;
  padding: 1px 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--navy);
  background-color: #FFFFFF;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.08);
}

/* Story Landing Page Styles */
.story-hero {
  text-align: center;
  padding: 44px 16px 36px;
  max-width: 860px;
  margin: 0 auto;
}
.story-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--trust-emerald-bg);
  color: var(--trust-emerald);
  border: 1px solid var(--trust-emerald-border);
  font-size: 12px;
  font-weight: 700;
  padding: 5px 16px;
  border-radius: 999px;
  margin-bottom: 20px;
  box-shadow: 0 1px 4px rgba(5, 150, 105, 0.12);
}
.story-headline {
  font-family: var(--font-serif);
  font-size: 42px;
  font-weight: 700;
  color: var(--navy);
  line-height: 1.2;
  letter-spacing: -0.02em;
  margin-bottom: 16px;
}
@media (max-width: 768px) {
  .story-headline { font-size: 28px; }
}
.story-highlight {
  color: #047857;
  font-family: var(--font-deva);
  background: linear-gradient(120deg, #ECFDF5 0%, #D1FAE5 100%);
  padding: 2px 12px;
  border-radius: 6px;
  border: 1px solid #A7F3D0;
  display: inline-block;
}
.story-lead {
  font-size: 16px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 700px;
  margin: 0 auto 28px;
}
.story-cta-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.btn-primary-hero {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  color: #FFFFFF;
  padding: 16px 36px;
  font-size: 15px;
  font-weight: 700;
  border-radius: var(--radius-sm);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 4px 16px rgba(5, 150, 105, 0.35);
  border: 1px solid #047857;
  transition: all 0.15s ease;
}
.btn-primary-hero:hover {
  background: linear-gradient(135deg, #10B981 0%, #059669 100%);
  box-shadow: 0 6px 20px rgba(5, 150, 105, 0.45);
  transform: translateY(-1px);
}
.story-cta-sub {
  font-size: 12px;
  color: var(--text-muted);
}
.story-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  margin: 36px 0;
}
.story-card {
  background: var(--card-bg);
  border-radius: var(--radius-sm);
  padding: 26px 28px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
}
.story-card.struggle {
  border: 1px solid #FECACA;
  border-top: 4px solid var(--alert-crimson);
  background: linear-gradient(180deg, #FFF5F5 0%, #FFFFFF 30%);
}
.story-card.breakthrough {
  border: 1px solid #A7F3D0;
  border-top: 4px solid #059669;
  background: linear-gradient(180deg, #F0FDF4 0%, #FFFFFF 30%);
}
.story-card-tag {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--alert-crimson);
  background: #FEE2E2;
  border: 1px solid #FECACA;
  display: inline-block;
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  margin-bottom: 8px;
}
.story-card-tag.breakthrough-tag {
  color: #047857;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
}
.story-card-title {
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 700;
  color: var(--navy);
  margin-bottom: 12px;
}
.story-card-text {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.55;
  margin-bottom: 16px;
}
.story-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 20px;
}
.story-list li {
  position: relative;
  padding-left: 20px;
}
.story-card.struggle .story-list li::before {
  content: "×";
  position: absolute;
  left: 0;
  top: -1px;
  color: var(--alert-crimson);
  font-weight: 800;
  font-size: 16px;
}
.story-card.breakthrough .story-list li::before {
  content: "✓";
  position: absolute;
  left: 0;
  top: 0px;
  color: #059669;
  font-weight: 800;
  font-size: 14px;
}
.story-card.struggle code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: #FEE2E2;
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  border: 1px solid #FECACA;
  color: #991B1B;
}
.story-card.breakthrough code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: #ECFDF5;
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  border: 1px solid #A7F3D0;
  color: #047857;
}
.story-card-footer {
  margin-top: auto;
  padding: 12px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}
.struggle-footer {
  color: #991B1B;
  background: #FEF2F2;
  border: 1px solid #FECACA;
}
.breakthrough-footer {
  color: #065F46;
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
}

.metrics-summary-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin: 34px 0;
}
.metric-item-card {
  background: #FFFFFF;
  border-radius: var(--radius-sm);
  padding: 22px 18px;
  text-align: center;
  box-shadow: var(--shadow-sm);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.metric-item-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
}
.metric-item-card.green {
  border: 1px solid #A7F3D0;
  border-top: 4px solid #059669;
  background: linear-gradient(180deg, #F0FDF4 0%, #FFFFFF 60%);
}
.metric-item-card.green .metric-stat { color: #059669; }

.metric-item-card.blue {
  border: 1px solid #BFDBFE;
  border-top: 4px solid #2563EB;
  background: linear-gradient(180deg, #EFF6FF 0%, #FFFFFF 60%);
}
.metric-item-card.blue .metric-stat { color: #2563EB; }

.metric-item-card.purple {
  border: 1px solid #DDD6FE;
  border-top: 4px solid #7C3AED;
  background: linear-gradient(180deg, #F5F3FF 0%, #FFFFFF 60%);
}
.metric-item-card.purple .metric-stat { color: #7C3AED; }

.metric-item-card.amber {
  border: 1px solid #FDE68A;
  border-top: 4px solid #D97706;
  background: linear-gradient(180deg, #FFFBEB 0%, #FFFFFF 60%);
}
.metric-item-card.amber .metric-stat { color: #D97706; }

.metric-stat {
  font-family: var(--font-mono);
  font-size: 26px;
  font-weight: 700;
  color: var(--navy);
  margin-bottom: 4px;
}
.metric-caption {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.story-bottom-cta {
  background: linear-gradient(135deg, #064E3B 0%, #065F46 45%, #0F172A 100%);
  border-radius: var(--radius-sm);
  padding: 44px 28px;
  text-align: center;
  margin-top: 44px;
  border: 1px solid rgba(16, 185, 129, 0.35);
  box-shadow: 0 10px 28px rgba(6, 78, 59, 0.25);
  color: #FFFFFF;
}
.btn-primary-white {
  background: #FFFFFF;
  color: #064E3B;
  padding: 14px 32px;
  font-size: 15px;
  font-weight: 700;
  border-radius: var(--radius-sm);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
  transition: all 0.15s ease;
}
.btn-primary-white:hover {
  background: #ECFDF5;
  color: #047857;
  transform: translateY(-1px);
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn-nav-action {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  color: #FFFFFF;
  padding: 9px 18px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-xs);
  border: 1px solid #047857;
  box-shadow: 0 2px 8px rgba(5, 150, 105, 0.25);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s ease;
}
.btn-nav-action:hover {
  background: linear-gradient(135deg, #10B981 0%, #059669 100%);
  box-shadow: 0 4px 14px rgba(5, 150, 105, 0.35);
  transform: translateY(-1px);
}
.link-subtle {
  font-size: 13px;
  color: var(--text-muted);
  text-decoration: none;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.link-subtle:hover {
  color: var(--navy);
}

/* How It Works Steps (Organized Cards) */
.how-section {
  margin: 48px 0 40px;
  padding: 36px 0 0;
  border-top: 1px solid var(--border);
}
.how-header {
  text-align: center;
  margin-bottom: 28px;
}
.how-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #059669;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.how-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.how-card {
  background: #FFFFFF;
  border-radius: var(--radius-sm);
  padding: 24px 22px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.how-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.09);
}
.how-card.step-1 {
  border: 1px solid #BFDBFE;
  border-top: 4px solid #2563EB;
  background: linear-gradient(180deg, #EFF6FF 0%, #FFFFFF 35%);
}
.how-card.step-1 .how-step-badge {
  background: #DBEAFE;
  color: #1E40AF;
  border: 1px solid #93C5FD;
}
.how-card.step-1 .how-icon-box {
  background: #EFF6FF;
  border: 1px solid #BFDBFE;
  color: #2563EB;
}
.how-card.step-1 .how-foot {
  color: #1E40AF;
  border-top: 1px solid #EFF6FF;
}

.how-card.step-2 {
  border: 1px solid #A7F3D0;
  border-top: 4px solid #059669;
  background: linear-gradient(180deg, #ECFDF5 0%, #FFFFFF 35%);
}
.how-card.step-2 .how-step-badge {
  background: #D1FAE5;
  color: #065F46;
  border: 1px solid #6EE7B7;
}
.how-card.step-2 .how-icon-box {
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  color: #059669;
}
.how-card.step-2 .how-foot {
  color: #065F46;
  border-top: 1px solid #ECFDF5;
}

.how-card.step-3 {
  border: 1px solid #DDD6FE;
  border-top: 4px solid #7C3AED;
  background: linear-gradient(180deg, #F5F3FF 0%, #FFFFFF 35%);
}
.how-card.step-3 .how-step-badge {
  background: #EDE9FE;
  color: #5B21B6;
  border: 1px solid #C4B5FD;
}
.how-card.step-3 .how-icon-box {
  background: #F5F3FF;
  border: 1px solid #DDD6FE;
  color: #7C3AED;
}
.how-card.step-3 .how-foot {
  color: #5B21B6;
  border-top: 1px solid #F5F3FF;
}

.how-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.how-step-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: var(--radius-xs);
}
.how-icon-box {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  justify-content: center;
}
.how-title {
  font-family: var(--font-serif);
  font-size: 17.5px;
  font-weight: 700;
  color: var(--navy);
  margin-bottom: 8px;
  line-height: 1.3;
}
.how-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.55;
  margin-bottom: 16px;
  flex: 1;
}
.how-foot {
  font-size: 11.5px;
  font-weight: 600;
  padding-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 960px) {
  .bento-col-4, .bento-col-6, .bento-col-8 { grid-column: span 12; }
  .metric-grid-4, .metric-grid-3, .about-grid, .guide-grid, .story-grid-2, .metrics-summary-bar, .how-grid { grid-template-columns: 1fr; }
  .action-card { flex-direction: column; gap: 16px; text-align: center; }
  .copilot-chat-panel { right: 12px; bottom: 80px; width: calc(100vw - 24px); }
  .flow-chain { flex-direction: column; }
}
"""

_LANDING_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>मिलान — 2-Hour GST Reconciliation in 5 Minutes</title>
  <style>__CSS__</style>
</head>
<body>
  <div class="wrap">
    <!-- Minimalist Navigation Header -->
    <header class="brand-header">
      <a href="/" class="brand-lockup" title="मिलान — Home">
        __MARK__
      </a>
      <div class="header-actions">
        <div class="badge-ca-desk">Chartered Accountant Tax Standard</div>
        <a href="/app" class="btn-nav-action">
          Enter Workspace
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </a>
      </div>
    </header>

    <!-- Story Hero Section -->
    <section class="story-hero">
      <div class="story-pill">
        <span>⚡</span> 2 Hours of Grunt Work &rarr; 5 Minutes of Autonomous Precision
      </div>
      <h1 class="story-headline">
        Your 2-Hour GST Reconciliation Headache.<br>
        Done in 5 Minutes with <span class="story-highlight">मिलान</span>.
      </h1>
      <p class="story-lead">
        Every month, audit teams waste endless billable hours manually cross-checking purchase registers against GSTR-2A/2B. Spotting invoice typos like <code>UP0068</code> vs <code>UPNUP0068</code>, off-by-one voucher slips, and vendor branch splits by hand is exhausting. <strong>मिलान</strong> eliminates the ordeal with local-first, multi-permutation matching.
      </p>
      <div class="story-cta-row">
        <a href="/app" class="btn-primary-hero">
          Enter मिलान Workspace
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </a>
        <div class="story-cta-sub">
          100% Confidential &middot; Runs locally on your machine &middot; No cloud upload &middot; Export 6-sheet audit Excel
        </div>
      </div>
    </section>

    <!-- Key Metrics Summary Bar -->
    <div class="metrics-summary-bar">
      <div class="metric-item-card green">
        <div class="metric-stat">2h &rarr; 5m</div>
        <div class="metric-caption">Audit time slashed per client per month</div>
      </div>
      <div class="metric-item-card blue">
        <div class="metric-stat">9 Stages</div>
        <div class="metric-caption">Multi-permutation deterministic matching</div>
      </div>
      <div class="metric-item-card purple">
        <div class="metric-stat">0% Cloud</div>
        <div class="metric-caption">Local Python memory execution &middot; Zero leaks</div>
      </div>
      <div class="metric-item-card amber">
        <div class="metric-stat">6 Sheets</div>
        <div class="metric-caption">Audit-ready executive workbook with Table 8</div>
      </div>
    </div>

    <!-- Act I vs Act II: The 2-Hour Struggle vs The 5-Minute Flow -->
    <div class="story-grid-2">
      <!-- The Struggle -->
      <div class="story-card struggle">
        <div class="story-card-tag">Before मिलान &middot; The 2-Hour Struggle</div>
        <div class="story-card-title">Manual VLOOKUPs, Typo Hell &amp; Eyestrain</div>
        <div class="story-card-text">
          Exporting portal data and purchase registers only to spend hours manually matching cell by cell:
        </div>
        <ul class="story-list">
          <li>
            <strong>Invoice Prefix Variances:</strong> Vendor types <code>UPNUP0068</code>, accountant enters <code>UP0068</code>. Standard VLOOKUP breaks, marking both as unreconciled.
          </li>
          <li>
            <strong>Clerical Off-By-One Slips:</strong> Voucher <code>4029</code> typed as <code>4030</code>. Two hours spent hunting down an apparent "missing" invoice.
          </li>
          <li>
            <strong>Multi-State Branch Splits:</strong> Supplier billed under Delhi GSTIN (<code>07...</code>) instead of Haryana (<code>06...</code>). Excel flags it as a missing vendor.
          </li>
          <li>
            <strong>Deadline Stress &amp; Rule 88D:</strong> Rushing to file GSTR-3B by the 20th without knowing your exact ITC mismatch exposure or DRC-01C risk.
          </li>
        </ul>
        <div class="story-card-footer struggle-footer">
          Result: 2+ hours lost per client &middot; High clerical fatigue &middot; Scrutiny exposure
        </div>
      </div>

      <!-- The Breakthrough -->
      <div class="story-card breakthrough">
        <div class="story-card-tag breakthrough-tag">With मिलान &middot; The 5-Minute Flow</div>
        <div class="story-card-title">Deterministic Multi-Permutation Engine</div>
        <div class="story-card-text">
          Drop your Tally/BUSY register and GSTR-2A into मिलान. It resolves discrepancies algorithmically:
        </div>
        <ul class="story-list">
          <li>
            <strong>Prefix &amp; Typo Bypass:</strong> Strips common prefixes, calculates string edit distances, and matches <code>UPNUP0068</code> &harr; <code>UP0068</code> into Partial Mismatch with tags.
          </li>
          <li>
            <strong>PAN Cross-Branch Routing:</strong> Matches across branches sharing the same 10-character PAN, ensuring valid credits aren't lost to different state GSTINs.
          </li>
          <li>
            <strong>Autonomous Scrutiny Shield:</strong> Reconciles Table 8A vs 8B gap and simulates Rule 88D demand liability with exact 10% / ₹25k threshold alerts.
          </li>
          <li>
            <strong>6-Sheet Master Excel:</strong> Generates executive color-coded working papers, vendor IMS matrix, and ready-to-send dispute letters in seconds.
          </li>
        </ul>
        <div class="story-card-footer breakthrough-footer">
          Result: Done in under 5 minutes &middot; Audit-proof working papers &middot; Partner ready
        </div>
      </div>
    </div>

    <!-- How It Works (3 Steps) -->
    <section class="how-section">
      <div class="how-header">
        <div class="how-kicker">3-MINUTE WORKFLOW</div>
        <h2 class="serif-title" style="font-size:26px;font-weight:700;margin-bottom:6px;">How मिलान Works in 3 Simple Steps</h2>
        <p style="font-size:14px;color:var(--text-secondary);margin:0;">No complex setup, no database configuration, and zero cloud telemetry.</p>
      </div>
      <div class="how-grid">
        <div class="how-card step-1">
          <div class="how-card-header">
            <span class="how-step-badge">STEP 01</span>
            <div class="how-icon-box">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            </div>
          </div>
          <h3 class="how-title">Export Columnar Register</h3>
          <p class="how-desc">
            Export your purchase register from Tally (<kbd class="kbd">F5</kbd> / <kbd class="kbd">Alt+E</kbd>) or BUSY using the built-in Columnar format, along with your GSTR-2A/2B Excel from the GST portal.
          </p>
          <div class="how-foot">
            <span style="font-weight:700;">✓</span> Standard Columnar Format
          </div>
        </div>

        <div class="how-card step-2">
          <div class="how-card-header">
            <span class="how-step-badge">STEP 02</span>
            <div class="how-icon-box">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            </div>
          </div>
          <h3 class="how-title">Drop into Local Workspace</h3>
          <p class="how-desc">
            Drag and drop your files into the मिलान workspace. The multi-permutation engine parses, matches, and classifies discrepancies entirely in local RAM.
          </p>
          <div class="how-foot">
            <span style="font-weight:700;">✓</span> 100% Local Machine Execution
          </div>
        </div>

        <div class="how-card step-3">
          <div class="how-card-header">
            <span class="how-step-badge">STEP 03</span>
            <div class="how-icon-box">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
          </div>
          <h3 class="how-title">Audit &amp; Download Report</h3>
          <p class="how-desc">
            Review the interactive discrepancy dashboard, examine vendor risk profiles, copy pre-drafted dispute notices, and download the 6-sheet audit Excel.
          </p>
          <div class="how-foot">
            <span style="font-weight:700;">✓</span> Audit-Proof Working Papers
          </div>
        </div>
      </div>
    </section>

    <!-- Bottom CTA Banner -->
    <div class="story-bottom-cta">
      <h2 style="font-family:var(--font-serif);font-size:26px;font-weight:700;color:#FFFFFF;margin-bottom:8px;">
        Reclaim your audit hours today.
      </h2>
      <p style="font-size:14px;color:var(--text-light);max-width:600px;margin:0 auto 24px;line-height:1.5;">
        Stop doing manual VLOOKUPs. Run autonomous GST reconciliation for your clients in under 5 minutes.
      </p>
      <a href="/app" class="btn-primary-white">
        Enter मिलान Workspace
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
      </a>
    </div>

    <!-- Minimalist Trust Footer -->
    <div class="trust-footer">
      मिलान &middot; Chartered Accountant Tax Standard &middot; 100% Local Standard Library Execution &middot; Zero Cloud Telemetry &middot; Strict Client Confidentiality
    </div>
  </div>
</body>
</html>
"""

_APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>मिलान — Client Reconciliation Workspace</title>
  <style>__CSS__</style>
</head>
<body>
  <!-- Micro-Animated Processing State Modal -->
  <div id="loader">
    <div class="loader-modal">
      <div class="spinner"></div>
      <h3 style="font-family:var(--font-serif);font-size:20px;font-weight:600;color:var(--navy);margin-bottom:6px;">Reconciling Client Books...</h3>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px;">Deterministic 3-way verification across books, portal, and statutory returns.</p>
      <div class="loader-steps">
        <div class="loader-step-item done"><span style="color:var(--trust-emerald);">✓</span> Inward Supply Schema Validation &amp; Parsing</div>
        <div class="loader-step-item done"><span style="color:var(--trust-emerald);">✓</span> 9-Stage Multi-Permutation Matching Engine</div>
        <div class="loader-step-item done"><span style="color:var(--trust-emerald);">✓</span> Compiling Table 8 Working Papers &amp; Scrutiny Shield</div>
      </div>
    </div>
  </div>

  <div class="wrap">
    <!-- Minimalist Navigation Header -->
    <header class="brand-header">
      <a href="/" class="brand-lockup" title="मिलान — Return to Home">
        __MARK__
      </a>
      <div class="header-meta">
        <div class="badge-ca-desk">Audit Desk &middot; File Upload</div>
        <div class="badge-status-secure">
          <span class="status-dot"></span>
          System Status: Secure &amp; Local
        </div>
      </div>
    </header>

    <!-- Workspace Header -->
    <div style="margin-bottom:24px;">
      <h1 class="hero-title" style="font-size:26px;">Attach Client Working Papers</h1>
      <p class="hero-sub" style="font-size:14px;">Upload your GSTR-2A/2B portal report and Tally / BUSY purchase register below to run the multi-permutation matching engine. Parsed deterministically in local memory with zero cloud telemetry.</p>
    </div>

    <!-- Hero / Upload Zone -->
    <div class="card">
      <div class="card-header-flex">
        <div>
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
            Select Client Files (.xlsx / .csv)
          </div>
          <div class="card-desc" style="margin-bottom:0;">
            Select or drag client files into the containers below. Supports multi-month purchase registers.
          </div>
        </div>
      </div>

      <form id="recon-form" method="post" action="/reconcile" enctype="multipart/form-data">
        <!-- In-Page File Error Alert Banner -->
        <div id="upload-error-banner" class="upload-error-banner" style="display:none;">
          <div class="err-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          </div>
          <div class="err-content">
            <div class="err-title" id="upload-error-title">File Selection Notice</div>
            <div class="err-msg" id="upload-error-msg"></div>
          </div>
          <button type="button" class="err-close" onclick="dismissErrorBanner()">&times;</button>
        </div>

        <div class="upload-grid">
          
          <label class="dropzone dz-portal" id="dz-2a" for="file-2a">
            <input type="file" name="gstr2a" id="file-2a" class="dz-hidden-input" accept=".xlsx,.csv" onchange="handleFileSelected(this, 'dz-2a')">
            <div class="dz-empty-state">
              <div class="dz-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
              </div>
              <span class="dz-pill req">Required Working Paper</span>
              <div class="dz-title">GSTR-2A / 2B Portal Export</div>
              <div class="dz-sub">Portal inward supply summary (.xlsx / .csv &middot; B2B &amp; CDNR)</div>
              <div class="dz-action-hint">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                Click to browse or drag file here
              </div>
            </div>

            <div class="dz-attached-state">
              <div class="dz-attached-check">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563EB" stroke-width="2.8"><polyline points="20 6 9 17 4 12"></polyline></svg>
              </div>
              <span class="dz-pill-attached">✓ Working Paper Attached</span>
              <div class="dz-attached-doc-type">GSTR-2A / 2B Portal Export</div>
              <div class="dz-file-card" id="name-dz-2a"></div>
              <div class="dz-attached-footer">
                <span class="dz-replace-text">Click card to replace file</span>
                <button type="button" class="dz-btn-remove" onclick="removeFile(event, 'file-2a', 'dz-2a')">✕ Remove</button>
              </div>
            </div>
          </label>

          <label class="dropzone dz-books" id="dz-tally" for="file-tally">
            <input type="file" name="tally" id="file-tally" class="dz-hidden-input" accept=".xlsx,.csv" multiple onchange="handleFileSelected(this, 'dz-tally')">
            <div class="dz-empty-state">
              <div class="dz-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
              </div>
              <span class="dz-pill req">Required Working Paper</span>
              <div class="dz-title">Tally or BUSY Purchase Register</div>
              <div class="dz-sub">Columnar Inward Register or DayBook (.xlsx / .csv &middot; Multi-file support)</div>
              <div class="dz-action-hint">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                Click to browse or drag files here
              </div>
            </div>

            <div class="dz-attached-state">
              <div class="dz-attached-check">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.8"><polyline points="20 6 9 17 4 12"></polyline></svg>
              </div>
              <span class="dz-pill-attached">✓ Working Paper Attached</span>
              <div class="dz-attached-doc-type">Tally / BUSY Purchase Register</div>
              <div class="dz-file-card" id="name-dz-tally"></div>
              <div class="dz-attached-footer">
                <span class="dz-replace-text">Click card to replace files</span>
                <button type="button" class="dz-btn-remove" onclick="removeFile(event, 'file-tally', 'dz-tally')">✕ Remove</button>
              </div>
            </div>
          </label>

          <label class="dropzone dz-gstr3b optional" id="dz-3b" for="file-3b">
            <input type="file" name="gstr3b" id="file-3b" class="dz-hidden-input" accept=".xlsx,.csv" onchange="handleFileSelected(this, 'dz-3b')">
            <div class="dz-empty-state">
              <div class="dz-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
              </div>
              <span class="dz-pill opt">Optional &middot; Unlocks Table 8</span>
              <div class="dz-title">GSTR-3B Monthly Return</div>
              <div class="dz-sub">12-month return summary for Table 8 flow &amp; Rule 88D shield</div>
              <div class="dz-action-hint">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                Click to browse or drag file here
              </div>
            </div>

            <div class="dz-attached-state">
              <div class="dz-attached-check">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7C3AED" stroke-width="2.8"><polyline points="20 6 9 17 4 12"></polyline></svg>
              </div>
              <span class="dz-pill-attached">✓ Table 8 Return Attached</span>
              <div class="dz-attached-doc-type">GSTR-3B Monthly Return</div>
              <div class="dz-file-card" id="name-dz-3b"></div>
              <div class="dz-attached-footer">
                <span class="dz-replace-text">Click card to replace file</span>
                <button type="button" class="dz-btn-remove" onclick="removeFile(event, 'file-3b', 'dz-3b')">✕ Remove</button>
              </div>
            </div>
          </label>

        </div>

        <div style="display:flex;align-items:center;justify-content:space-between;padding-top:16px;border-top:1px solid var(--border);flex-wrap:wrap;gap:14px;">
          <div style="font-size:12.5px;color:var(--text-muted);display:flex;align-items:center;gap:6px;">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
            Zero cloud telemetry &middot; 100% deterministic Python standard library &middot; Strict client confidentiality
          </div>
          <button type="submit" class="btn-primary" id="btn-submit-recon">
            Reconcile Client Books &rarr;
          </button>
        </div>
      </form>
    </div>

    <!-- Section: How to Fetch Purchase Register (Scroll Down) -->
    <div class="guide-section">
      <div class="guide-header">
        <h2 class="serif-title" style="font-size:22px;margin-bottom:4px;">How to Export Your Purchase Register</h2>
        <p style="font-size:13px;color:var(--text-secondary);margin:0;">To enable automated invoice matching and tax ledger verification, export your purchase register in <strong>Columnar format</strong>. Follow the step-by-step instructions for your accounting software below.</p>
      </div>

      <div class="guide-grid">
        
        <!-- Tally Guide -->
        <div class="guide-card tally">
          <div class="guide-card-header">
            <div class="guide-app-title">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#D97706" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
              Tally (Prime &amp; ERP 9)
            </div>
            <span class="guide-badge">Columnar Register</span>
          </div>
          <div class="guide-steps">
            <div class="guide-step-item">
              <span class="guide-step-num">1</span>
              <span>Go to <strong>Gateway of Tally</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">2</span>
              <span>Select <strong>Display</strong> or <strong>Display More Reports</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">3</span>
              <span>Select <strong>Account Books</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">4</span>
              <span>Select <strong>Purchase Register</strong> and press <kbd class="kbd">Enter</kbd> for the required month.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">5</span>
              <span>Click <kbd class="kbd">F5: Columnar</kbd> (or <kbd class="kbd">F8: Columnar</kbd>) from the right-side button bar.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">6</span>
              <span>Set the required display options (such as showing supplier invoice details, date, or specific ledgers) to <strong>Yes</strong>, then press <kbd class="kbd">Enter</kbd>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">7</span>
              <span>Once the columnar register is displayed on your screen, press <kbd class="kbd">Alt + E</kbd> (Export) and select <strong>Current</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">8</span>
              <span>Press <kbd class="kbd">C</kbd> (Configure) if you want to change the file format (Excel, PDF, or CSV). Select <strong>Excel</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">9</span>
              <span>Press <kbd class="kbd">E</kbd> (Send/Export) to download and save the file to your computer.</span>
            </div>
          </div>
        </div>

        <!-- BUSY Guide -->
        <div class="guide-card busy">
          <div class="guide-card-header">
            <div class="guide-app-title">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563EB" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
              BUSY Accounting Software
            </div>
            <span class="guide-badge">Columnar Register</span>
          </div>
          <div class="guide-steps">
            <div class="guide-step-item">
              <span class="guide-step-num">1</span>
              <span>Go to the <strong>Display menu</strong> on the main gateway of BUSY.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">2</span>
              <span>Click on <strong>Account Books</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">3</span>
              <span>Select <strong>Account Registers (Standard)</strong> and <strong>Columnar</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">4</span>
              <span>Click on <strong>Purchase Register</strong>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">5</span>
              <span>Select <strong>Columnar</strong> (instead of Standard).</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">6</span>
              <span>Click the <strong>Export</strong> button on the top toolbar or use the shortcut key <kbd class="kbd">Alt + E</kbd>.</span>
            </div>
            <div class="guide-step-item">
              <span class="guide-step-num">7</span>
              <span>Choose your preferred Data Format (<strong>Excel / .xlsx</strong>) to export and save the file.</span>
            </div>
          </div>
        </div>

      </div>

      <div class="guide-note">
        <strong>Auditor's Note:</strong> The Columnar register format exports separate columns for Supplier GSTIN, Voucher/Invoice No., Voucher Date, Taxable Value, CGST, SGST, and IGST. This enables Milan to run multi-permutation matching across all tax ledgers with zero manual reformatting.
      </div>
    </div>

    <div class="trust-footer">
      मिलान &middot; Chartered Accountant Tax Standard &middot; 100% Local Standard Library Execution &middot; Zero Cloud Telemetry &middot; Strict Client Confidentiality
    </div>

  </div>

  <script>
    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      var k = 1024;
      var sizes = ['B', 'KB', 'MB', 'GB'];
      var i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function escapeHtml(s) {
      var div = document.createElement('div');
      div.textContent = s || '';
      return div.innerHTML;
    }

    function showErrorBanner(msg, title) {
      var b = document.getElementById('upload-error-banner');
      var t = document.getElementById('upload-error-title');
      var m = document.getElementById('upload-error-msg');
      if (t) t.textContent = title || 'File Selection Notice';
      if (m) m.textContent = msg;
      if (b) {
        b.style.display = 'flex';
        b.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    function dismissErrorBanner() {
      var b = document.getElementById('upload-error-banner');
      if (b) b.style.display = 'none';
    }

    function handleFileSelected(input, dzId) {
      dismissErrorBanner();
      var dz = document.getElementById(dzId);
      var nameBox = document.getElementById('name-' + dzId);
      if (!dz) return;
      if (input.files && input.files.length > 0) {
        dz.classList.add('has-file');
        if (nameBox) {
          if (input.files.length === 1) {
            var f = input.files[0];
            var ext = f.name.split('.').pop().toUpperCase() || 'XLSX';
            nameBox.innerHTML = '<div class="dz-file-row">' +
              '<span class="dz-file-ext-icon">' + escapeHtml(ext) + '</span>' +
              '<div class="dz-file-meta">' +
                '<span class="dz-file-title" title="' + escapeHtml(f.name) + '">' + escapeHtml(f.name) + '</span>' +
                '<span class="dz-file-size">' + formatBytes(f.size) + ' &middot; Verified &amp; Ready</span>' +
              '</div>' +
            '</div>';
          } else {
            var totalSize = 0;
            for (var j = 0; j < input.files.length; j++) totalSize += input.files[j].size;
            nameBox.innerHTML = '<div class="dz-file-row">' +
              '<span class="dz-file-ext-icon">XLSX</span>' +
              '<div class="dz-file-meta">' +
                '<span class="dz-file-title">' + input.files.length + ' Working Paper Files Attached</span>' +
                '<span class="dz-file-size">' + formatBytes(totalSize) + ' total &middot; Multi-file merged</span>' +
              '</div>' +
            '</div>';
          }
        }
      } else {
        dz.classList.remove('has-file');
        if (nameBox) {
          nameBox.innerHTML = '';
        }
      }
      updateReconChecklist();
    }

    function removeFile(e, inputId, dzId) {
      if (e) {
        e.stopPropagation();
        e.preventDefault();
      }
      var input = document.getElementById(inputId);
      if (input) {
        input.value = '';
        handleFileSelected(input, dzId);
      }
    }

    function updateReconChecklist() {
      var f2a = document.getElementById('file-2a');
      var ftally = document.getElementById('file-tally');
      var f3b = document.getElementById('file-3b');
      var summaryBox = document.getElementById('upload-status-summary');
      if (!summaryBox) return;

      var has2a = f2a && f2a.files && f2a.files.length > 0;
      var hasTally = ftally && ftally.files && ftally.files.length > 0;
      var has3b = f3b && f3b.files && f3b.files.length > 0;

      if (has2a && hasTally) {
        var extra3b = has3b ? ' + GSTR-3B Table 8' : '';
        summaryBox.innerHTML = '<span style="color:#047857;font-weight:700;display:inline-flex;align-items:center;gap:6px;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg> Both Required Files Attached' + extra3b + ' &middot; Click below to Reconcile</span>';
      } else if (has2a) {
        summaryBox.innerHTML = '<span style="color:#2563EB;font-weight:600;">✓ GSTR-2A attached &middot; Next: Attach Tally or BUSY Purchase Register</span>';
      } else if (hasTally) {
        summaryBox.innerHTML = '<span style="color:#059669;font-weight:600;">✓ Purchase Register attached &middot; Next: Attach GSTR-2A Portal Export</span>';
      } else {
        summaryBox.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg> Zero cloud telemetry &middot; 100% deterministic Python standard library &middot; Strict client confidentiality';
      }
    }

    // Pre-flight validation on form submission
    var form = document.getElementById('recon-form');
    if (form) {
      form.addEventListener('submit', function(e) {
        dismissErrorBanner();
        var f2a = document.getElementById('file-2a');
        var ftally = document.getElementById('file-tally');

        if (!f2a || !f2a.files || !f2a.files.length) {
          e.preventDefault();
          showErrorBanner('Please attach your GSTR-2A / 2B Portal Export file (.xlsx / .csv).', 'Required File Missing');
          return;
        }
        if (!ftally || !ftally.files || !ftally.files.length) {
          e.preventDefault();
          showErrorBanner('Please attach your Tally or BUSY Purchase Register file (.xlsx / .csv).', 'Required File Missing');
          return;
        }

        var loader = document.getElementById('loader');
        if (loader) loader.style.display = 'flex';
      });
    }

    // Prevent default dragover/drop on window so misses don't open the file
    window.addEventListener('dragover', function(e) { e.preventDefault(); }, false);
    window.addEventListener('drop', function(e) { e.preventDefault(); }, false);

    // Drag-and-drop listener enhancement with DataTransfer
    var dropzones = document.querySelectorAll('.dropzone');
    dropzones.forEach(function(dz) {
      ['dragenter', 'dragover'].forEach(function(evt) {
        dz.addEventListener(evt, function(e) {
          e.preventDefault();
          e.stopPropagation();
          dz.classList.add('dragover');
        });
      });

      ['dragleave', 'dragend'].forEach(function(evt) {
        dz.addEventListener(evt, function(e) {
          e.preventDefault();
          e.stopPropagation();
          dz.classList.remove('dragover');
        });
      });

      dz.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dz.classList.remove('dragover');
        var dt = e.dataTransfer;
        if (!dt || !dt.files || !dt.files.length) return;
        var forId = dz.getAttribute('for');
        var fileInput = document.getElementById(forId) || dz.querySelector('input[type="file"]');
        if (!fileInput) return;
        try {
          fileInput.files = dt.files;
        } catch (err1) {
          try {
            var transfer = new DataTransfer();
            if (fileInput.multiple) {
              for (var i = 0; i < dt.files.length; i++) transfer.items.add(dt.files[i]);
            } else {
              transfer.items.add(dt.files[0]);
            }
            fileInput.files = transfer.files;
          } catch (err2) {
            console.error("Drop assignment error", err2);
          }
        }
        handleFileSelected(fileInput, dz.id);
      });
    });
  </script>
</body>
</html>
"""

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>मिलान — GST Tax Reconciliation</title>
  <style>__CSS__</style>
</head>
<body>
  <div id="toast">Notice copied to clipboard!</div>

  <div class="wrap">
    <!-- Minimalist Navigation Header -->
    <header class="brand-header">
      <a href="/" class="brand-lockup" title="मिलान — Return to Home">
        __MARK__
        <span class="brand-sep">/</span>
        <span class="brand-stats">__GSTR_COUNT__ portal bills &middot; __TALLY_COUNT__ books bills &middot; __MATCH_COUNT__ confirmed matches</span>
      </a>
      <div class="header-meta">
        <div class="badge-ca-desk">Audit Desk &middot; Partner View</div>
        <div class="badge-status-secure">
          <span class="status-dot"></span>
          System Status: Secure &amp; Encrypted &middot; Local Execution
        </div>
      </div>
    </header>

    <!-- Navigation Tabs (4 Core Pillars) -->
    <div class="tabs-nav">
      <button class="tab-btn active" onclick="switchTab('tab-recon', this)">📊 Reconciliation Summary &amp; Table 8</button>
      <button class="tab-btn" onclick="switchTab('tab-forecaster', this)">🛡️ Rule 88D &amp; Cash Forecaster</button>
      <button class="tab-btn" onclick="switchTab('tab-vendors', this)">🏢 Vendor IMS Matrix</button>
      <button class="tab-btn" onclick="switchTab('tab-drafter', this)">⚖️ Dispute Notice Drafter</button>
    </div>

    <!-- TAB 1: Recon & Table 8 (Bento Grid) -->
    <div id="tab-recon" class="tab-pane active">
      
      <div class="bento-grid">
        
        <!-- Bento Card A: Total Files Uploaded & Scope -->
        <div class="bento-col-4">
          <div class="metric-card" style="height:100%;">
            <div class="metric-label">Audit Scope &amp; Inward Volume (Card A)</div>
            <div class="metric-val">__TOTAL_FILES__ Files &middot; __TOTAL_RECORDS__ Records</div>
            <div class="metric-sub" style="margin-top:8px;">
              <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
                <span>GSTR-2A Portal:</span>
                <strong style="font-family:var(--font-mono);color:var(--navy);">__GSTR_COUNT__ bills (__AVAIL_2A__)</strong>
              </div>
              <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
                <span>Books Purchase Ledger:</span>
                <strong style="font-family:var(--font-mono);color:var(--navy);">__TALLY_COUNT__ bills (__BOOKED_TALLY__)</strong>
              </div>
              <div style="display:flex;justify-content:space-between;padding:4px 0;">
                <span>Discrepancies Flagged:</span>
                <strong style="font-family:var(--font-mono);color:var(--alert-crimson);">__DISCREPANCY_COUNT__ items</strong>
              </div>
            </div>
          </div>
        </div>

        <!-- Bento Card B: Reconciliation Accuracy Rate (Donut Chart) -->
        <div class="bento-col-4">
          <div class="metric-card accent" style="height:100%;">
            <div class="metric-label">Reconciliation Accuracy Rate (Card B)</div>
            <div class="donut-box">
              <div class="donut-svg-wrap">
                <svg class="donut-svg" width="96" height="96" viewBox="0 0 100 100">
                  <circle class="donut-bg" cx="50" cy="50" r="40" stroke="#E2E8F0" stroke-width="10" fill="none"/>
                  <circle class="donut-val" cx="50" cy="50" r="40" stroke="#15803D" stroke-width="10" fill="none"
                          stroke-dasharray="__DONUT_DASH__" stroke-dashoffset="0" stroke-linecap="round"/>
                </svg>
                <div class="donut-center-text">
                  <span class="donut-pct">__ACCURACY_RATE__</span>
                  <span class="donut-sub">Matched</span>
                </div>
              </div>
              <div class="donut-meta">
                <div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:var(--trust-emerald);">__MATCHED_TAX__</div>
                <div style="font-size:12px;color:var(--text-secondary);">Verified Eligible ITC</div>
                <div style="margin-top:4px;">
                  <span class="status-pill claim">✓ __MATCH_COUNT__ Confirmed Pairs</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Bento Card D: Section 16(4) Lapse Exposure -->
        <div class="bento-col-4">
          <div class="metric-card danger" style="height:100%;">
            <div class="metric-label">Statutory Action Required u/s 16(4)</div>
            <div class="metric-val" style="color:var(--alert-crimson);">__UNCLAIMED_TAX__</div>
            <div class="metric-sub" style="margin-top:6px;line-height:1.45;">
              __UNCLAIMED_COUNT__ Inward supplies verified on portal that your client never booked in accounting software.
            </div>
            <div style="margin-top:10px;">
              <span class="status-pill reverse">Lapses 30 Nov 2026 &middot; __DAYS_LEFT__d Left</span>
            </div>
          </div>
        </div>

        <!-- Bento Card C: "Discrepancies Flagged" (High-Density Data Table) -->
        <div class="bento-col-12">
          <div class="card" style="margin-bottom:0;">
            <div class="card-header-flex">
              <div>
                <div class="card-title">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                  Discrepancies Flagged &amp; Categorized Findings (Card C)
                </div>
                <div class="card-desc" style="margin-bottom:0;">
                  High-density ledger versus portal mismatch analysis. Every discrepancy is classified by statutory tax remedy.
                </div>
              </div>
              <div class="table-search-box" style="min-width:280px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                <input type="text" id="recon-search" placeholder="Filter category or statutory remedy..." onkeyup="filterReconTable()">
              </div>
            </div>

            <table id="recon-table">
              <thead>
                <tr>
                  <th>Category / Discrepancy Nature</th>
                  <th class="n">Bills</th>
                  <th class="n">ITC Value</th>
                  <th>Actionable Tax Remedy</th>
                </tr>
              </thead>
              <tbody>
                __RECON_ROWS__
              </tbody>
            </table>
          </div>
        </div>

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
        <div style="background:var(--trust-emerald-bg);padding:14px 18px;border-radius:var(--radius-xs);border-left:4px solid var(--trust-emerald);font-size:13px;color:var(--text-secondary);">
          <strong style="color:var(--trust-emerald);">Statutory Compliance Defense:</strong> __R88_REMEDY__
        </div>
      </div>

      <div class="card">
        <div class="card-title">Forward Cash Outflow &amp; Working Capital Position</div>
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
        <div class="card-header-flex">
          <div>
            <div class="card-title">Vendor Compliance Scorecards &amp; IMS Directives</div>
            <div class="card-desc" style="margin-bottom:0;">Evaluates __TOTAL_VENDORS__ suppliers across filing timeliness, multi-state registrations, and tax accuracy.</div>
          </div>
          <div class="table-search-box" style="min-width:280px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <input type="text" id="vendor-search" placeholder="Search supplier or GSTIN..." onkeyup="filterVendors()">
          </div>
        </div>

        <table id="vendor-table">
          <thead>
            <tr>
              <th>Grade</th>
              <th>Supplier Name &amp; GSTIN</th>
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
        <h3>Export Reconciled Master Sheet</h3>
        <p>Complete six-sheet working papers: Executive Summary, Matched Bills, Not in 2A, Partial Mismatch, Not in Tally, and Table 8 Position.</p>
      </div>
      <div>
        <a class="btn-download" href="#" onclick="milanDownload('xlsx');return false;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Export Reconciled Master Sheet (.xlsx)
        </a>
        <a class="btn-download alt" href="#" onclick="milanDownload('csv');return false;">Download Audit Trail (.csv)</a>
      </div>
    </div>

    <div class="nav-back">
      <a href="/app">← Reconcile another client</a>
    </div>

    <div class="trust-footer">
      मिलान &middot; Chartered Accountant Tax Standard &middot; 100% Local Standard Library Execution &middot; Zero Cloud Telemetry &middot; Strict Client Confidentiality
    </div>

  </div>

  <!-- FLOATING COPILOT CHATBOT (BOTTOM RIGHT) -->
  <button class="copilot-trigger" onclick="toggleCopilotChat()">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
    <span>✨ Ask FinOps Co-Pilot</span>
  </button>

  <div id="copilot-chat" class="copilot-chat-panel">
    <div class="copilot-header">
      <div>
        <div class="copilot-header-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>
          FinOps Controller Co-Pilot
        </div>
        <div class="copilot-header-sub">100% Fact-Grounded &middot; Zero Hallucination</div>
      </div>
      <button class="copilot-close" onclick="toggleCopilotChat()">✕</button>
    </div>

    <div id="copilot-chat-body" class="copilot-body">
      <div class="chat-msg copilot">
        <strong style="color:var(--navy);">👋 Hello! I am your AI Finance Controller.</strong>
        <p style="margin-top:4px;color:var(--text-secondary);">Ask me anything about your GST books, Rule 88D risk, Section 16(4) lapse, or delinquent vendors.</p>
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

    // Everything the page needs after render: the two generated files and every
    // copilot answer. Embedded because on serverless the next request may hit a
    // different, cold instance that never saw this reconciliation.
    var MILAN = __EMBED_JSON__;

    function milanDownload(kind) {
      var f = MILAN.files[kind];
      if (!f) { alert('That file is not available for this run.'); return; }
      var bin = atob(f.b64);
      var buf = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) { buf[i] = bin.charCodeAt(i); }
      var url = URL.createObjectURL(new Blob([buf], {type: f.mime}));
      var a = document.createElement('a');
      a.href = url; a.download = f.name;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
    }

    function milanAnswer(q) {
      var lower = (q || '').toLowerCase().trim();
      for (var t = 0; t < MILAN.copilot.topics.length; t++) {
        var topic = MILAN.copilot.topics[t];
        for (var k = 0; k < topic.keywords.length; k++) {
          if (lower.indexOf(topic.keywords[k]) !== -1) { return topic; }
        }
      }
      return MILAN.copilot.fallback;
    }

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

    function filterReconTable() {
      var query = document.getElementById('recon-search').value.toLowerCase();
      var rows = document.querySelectorAll('#recon-table tbody tr');
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
      var userMsg = document.createElement('div');
      userMsg.className = 'chat-msg user';
      userMsg.textContent = q;
      body.appendChild(userMsg);

      input.value = '';
      scrollChatToBottom();

      var loadingBubble = document.createElement('div');
      loadingBubble.className = 'chat-msg copilot';
      loadingBubble.innerHTML = "<span style='color:var(--text-muted);'>Analyzing factual records...</span>";
      body.appendChild(loadingBubble);
      scrollChatToBottom();

      // Answers were computed server-side at reconcile time by the same
      // ask_copilot() the CLI uses, then embedded. Routing the question to one
      // of them is a keyword match, so it needs no server round trip -- which
      // is what makes it survive a cold serverless instance.
      setTimeout(function() {
        try {
          var data = milanAnswer(q);
          var content = "<div style='font-size:14px;font-weight:700;color:var(--navy);margin-bottom:6px;'>" + data.headline + "</div>";
          content += "<div style='color:var(--navy);line-height:1.5;'>" + data.answer_html + "</div>";

          if (data.action_items && data.action_items.length) {
            content += "<div style='margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:11px;font-weight:700;text-transform:uppercase;color:var(--text-muted);'>Action Checklist:</div><ul style='margin-left:16px;font-size:12px;color:var(--text-secondary);'>";
            for (var k = 0; k < data.action_items.length; k++) {
              content += "<li>" + data.action_items[k] + "</li>";
            }
            content += "</ul>";
          }
          loadingBubble.innerHTML = content;
        } catch (err) {
          loadingBubble.innerHTML = "<div style='color:var(--alert-crimson);'>Error reading Co-Pilot data: " + err.toString() + "</div>";
        }
        scrollChatToBottom();
      }, 120);
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

    def _authorised(self) -> bool:
        """HTTP Basic against MILAN_PASSWORD. No password configured means no
        gate, which is correct when bound to 127.0.0.1 and wrong the moment the
        app has a public URL -- it handles a real client's GSTINs, supplier
        list and complete tax position."""
        if not _PASSWORD:
            return True
        supplied = self.headers.get("Authorization", "")
        if supplied.startswith("Basic "):
            try:
                decoded = base64.b64decode(supplied[6:]).decode("utf-8", "replace")
                _, _, pw = decoded.partition(":")
                if hmac.compare_digest(pw, _PASSWORD):   # constant time
                    return True
            except Exception:
                pass
        try:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Milan"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True
        return False

    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

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
        if not self._authorised():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self._send(_LANDING_HTML.replace("__CSS__", _CSS).replace("__MARK__", _MARK))

        if path in ("/app", "/workspace"):
            return self._send(_APP_HTML.replace("__CSS__", _CSS).replace("__MARK__", _MARK))

        if path in ("/demo", "/reconcile"):
            self.send_response(302)
            self.send_header("Location", "/app")
            self.end_headers()
            return

        if path == "/swap-reconcile":
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get("token", [""])[0]
            session = _SWAP_SESSIONS.get(token)
            if not session:
                return self._send(_render_error_page(
                    title="Please Check Your Uploaded Files Again",
                    message="The upload session has expired or is invalid. Please return to the workspace and re-attach your files.",
                    show_checklist=True,
                ), 400)
            try:
                gstr_path = session["gstr_path"]
                tally_paths = session["tally_paths"]
                gstr3b_path = session.get("gstr3b_path")
                folder = session["folder"]

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
                    "created_at": time.time(),
                }
                del _SWAP_SESSIONS[token]
                return self._send(_render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions,
                                            embed=_build_embed(folder, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary)))
            except Exception as exc:
                return self._send(_render_error_page(
                    title="Please Check Your Uploaded Files Again",
                    message="Could not auto-reconcile the swapped files. Please check your files again and re-attach them in the workspace.",
                    details=str(exc),
                    show_checklist=True,
                ), 400)

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
        if not self._authorised():
            return
        if self.path != "/reconcile":
            return self._send(_render_error_page("Page Not Found", "The requested reconciliation endpoint does not exist."), 404)

        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            return self._send(_render_error_page("Malformed Upload", "The upload stream was incomplete or missing multipart boundaries. Please re-select the files and submit again."), 400)
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return self._send(_render_error_page("Files Too Large", "The attached files exceed the 64 MB maximum upload limit. Please verify that you are uploading standard monthly purchase registers."), 413)

        boundary = ctype.split("boundary=", 1)[1].strip('"').encode()
        parts = _parse_multipart(self.rfile.read(length), boundary)

        _cleanup_old_sessions()
        token = uuid.uuid4().hex
        folder = _TMP / token
        folder.mkdir(parents=True, exist_ok=True)

        gstr_path, tally_paths, gstr3b_path = None, [], None
        for field, fname, data in parts:
            if not data or not fname:
                continue
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
            return self._send(_render_error_page(
                title="Missing Required Working Papers",
                message="Reconciliation requires both: (1) GSTR-2A/2B Portal Export and (2) Tally or BUSY Purchase Register. Please check your files and ensure both are attached before clicking Reconcile.",
                show_checklist=True,
            ), 400)

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
            # Check if user swapped the files (Purchase Register in 2A slot, and 2A in Tally slot)
            is_swapped = False
            if len(tally_paths) == 1:
                try:
                    test_gstr = load_gstr2a(str(tally_paths[0]))
                    test_tally, _ = load_tally([str(gstr_path)])
                    if test_gstr and test_tally:
                        is_swapped = True
                except Exception:
                    pass

            pr_markers = ["party", "doc. no", "particulars", "voucher type", "voucher no", "error description", "gstr-2 section"]
            exc_str = str(exc).lower()
            looks_like_pr_in_2a = any(k in exc_str for k in pr_markers)

            if is_swapped:
                _SWAP_SESSIONS[token] = {
                    "gstr_path": tally_paths[0],
                    "tally_paths": [gstr_path],
                    "gstr3b_path": gstr3b_path,
                    "folder": folder,
                }
                return self._send(_render_error_page(
                    title="Please Check Your Uploaded Files Again",
                    message="The uploaded files could not be reconciled. Your Purchase Register was attached in the GSTR-2A field, and GSTR-2A was attached in the Purchase Register field.",
                    details=str(exc),
                    is_swapped=True,
                    token=token,
                    show_checklist=True,
                ), 400)
            elif looks_like_pr_in_2a:
                shutil.rmtree(folder, ignore_errors=True)
                return self._send(_render_error_page(
                    title="Please Check Your Uploaded Files Again",
                    message="The uploaded files could not be reconciled. It appears your Purchase Register was attached in the GSTR-2A field instead of the Purchase Register field.",
                    details=str(exc),
                    is_swapped=False,
                    show_checklist=True,
                ), 400)
            else:
                shutil.rmtree(folder, ignore_errors=True)
                return self._send(_render_error_page(
                    title="Please Check Your Uploaded Files Again",
                    message="The uploaded spreadsheets could not be processed. Please check your files again and make sure each file is attached in its designated container.",
                    details=str(exc),
                    is_swapped=False,
                    show_checklist=True,
                ), 400)

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
            "created_at": time.time(),
        }

        self._send(_render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions,
                                            embed=_build_embed(folder, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary)))


def _render_error_page(
    title: str,
    message: str,
    details: str = "",
    is_swapped: bool = False,
    token: str = "",
    show_checklist: bool = False,
) -> str:
    is_check_files = show_checklist or is_swapped or "Check Your" in title

    top_border = "border-top: 4px solid var(--warning-amber);" if is_check_files else "border-top: 4px solid var(--alert-crimson);"
    icon_bg = "var(--warning-amber-bg)" if is_check_files else "#FEE2E2"
    icon_border = "var(--warning-amber-border)" if is_check_files else "#FECACA"
    icon_color = "var(--warning-amber)" if is_check_files else "#DC2626"

    if is_check_files:
        icon_svg = (
            '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>'
            '<polyline points="14 2 14 8 20 8"></polyline>'
            '<line x1="12" y1="18" x2="12" y2="12"></line>'
            '<line x1="9" y1="15" x2="15" y2="15"></line>'
            '</svg>'
        )
    else:
        icon_svg = (
            '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">'
            '<circle cx="12" cy="12" r="10"></circle>'
            '<line x1="12" y1="8" x2="12" y2="12"></line>'
            '<line x1="12" y1="16" x2="12.01" y2="16"></line>'
            '</svg>'
        )

    swapped_alert_html = ""
    if is_swapped:
        swapped_alert_html = (
            '<div style="background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #D97706;'
            'border-radius:4px;padding:12px 16px;text-align:left;max-width:560px;margin:0 auto 20px;'
            'font-size:13.5px;color:#92400E;line-height:1.5;">'
            '<strong>Swapped Files Detected:</strong> Your Purchase Register was attached in the GSTR-2A container, '
            'and GSTR-2A was attached in the Purchase Register container.'
            '</div>'
        )

    checklist_html = ""
    if show_checklist or is_swapped:
        checklist_html = (
            '<div style="background:#F8FAFC;border:1px solid #CBD5E1;border-radius:6px;padding:18px 22px;'
            'text-align:left;max-width:560px;margin:0 auto 22px;">'
            '<div style="font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:0.06em;'
            'color:var(--text-muted);text-transform:uppercase;margin-bottom:12px;">'
            'How to verify your files before re-submitting:'
            '</div>'
            '<div style="display:flex;flex-direction:column;gap:12px;font-size:13.5px;line-height:1.5;color:var(--text-secondary);">'
            '<div style="display:flex;gap:10px;align-items:flex-start;">'
            '<span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;'
            'border-radius:50%;background:var(--trust-emerald-bg);color:var(--trust-emerald);font-weight:700;'
            'font-size:11px;flex-shrink:0;">1</span>'
            '<div><strong style="color:var(--navy);">GSTR-2A / 2B Field:</strong> Attach your official GSTR-2A or GSTR-2B file downloaded directly from the GST Portal (.xlsx or .csv).</div>'
            '</div>'
            '<div style="display:flex;gap:10px;align-items:flex-start;">'
            '<span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;'
            'border-radius:50%;background:var(--trust-emerald-bg);color:var(--trust-emerald);font-weight:700;'
            'font-size:11px;flex-shrink:0;">2</span>'
            '<div><strong style="color:var(--navy);">Purchase Register Field:</strong> Attach your Purchase Register exported from Tally (Columnar format: <code style="background:#E2E8F0;padding:1px 4px;border-radius:3px;font-size:11px;">F5: Columnar</code>) or BUSY (.xlsx or .csv).</div>'
            '</div>'
            '<div style="display:flex;gap:10px;align-items:flex-start;">'
            '<span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;'
            'border-radius:50%;background:var(--warning-amber-bg);color:var(--warning-amber);font-weight:700;'
            'font-size:11px;flex-shrink:0;">!</span>'
            '<div><strong style="color:var(--navy);">Check for Swapped Sheets:</strong> Ensure that the Purchase Register is not placed into the GSTR-2A field, and GSTR-2A is not placed into the Purchase Register field.</div>'
            '</div>'
            '</div>'
            '</div>'
        )

    auto_swap_btn = ""
    if is_swapped and token:
        auto_swap_btn = (
            f'<a href="/swap-reconcile?token={html.escape(token)}" style="text-decoration:none;padding:10px 18px;'
            f'font-size:13.5px;font-weight:600;color:var(--brand-emerald);background:var(--brand-emerald-soft);'
            f'border:1px solid var(--brand-emerald-light);border-radius:4px;display:inline-flex;align-items:center;gap:6px;'
            f'transition:background 0.15s ease;" title="Auto-swap the two files and reconcile directly">'
            f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">'
            f'<path d="M7 16V4M7 4L3 8M7 4l4 4M17 8v12M17 20l-4-4M17 20l4-4"/>'
            f'</svg>'
            f'Auto-Swap Files &amp; Reconcile Now'
            f'</a>'
        )

    details_html = ""
    if details:
        details_html = (
            f'<details style="margin-top:24px;text-align:left;max-width:560px;margin-left:auto;margin-right:auto;">'
            f'<summary style="cursor:pointer;color:var(--text-light);font-size:11px;font-family:var(--font-mono);user-select:none;">Technical Diagnostics (for developers)</summary>'
            f'<div style="margin-top:8px;background:#F8FAFC;border:1px solid #CBD5E1;border-radius:4px;padding:10px 12px;font-family:var(--font-mono);font-size:11px;color:#475569;overflow-x:auto;white-space:pre-wrap;">{html.escape(details)}</div>'
            f'</details>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"><title>{html.escape(title)} — मिलान</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="wrap" style="max-width:720px;margin-top:40px;">
    <header class="brand-header">
      <a href="/" class="brand-lockup" title="मिलान — Return to Home">
        {_MARK}
      </a>
      <div class="badge-ca-desk">Chartered Accountant Tax Standard</div>
    </header>

    <div class="card" style="{top_border}padding:36px 30px;text-align:center;">
      <div style="width:60px;height:60px;border-radius:50%;background:{icon_bg};border:1px solid {icon_border};color:{icon_color};display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
        {icon_svg}
      </div>
      <h2 class="serif-title" style="font-size:24px;color:var(--navy);margin-bottom:12px;">{html.escape(title)}</h2>
      <p style="font-size:14.5px;color:var(--text-secondary);max-width:540px;margin:0 auto 18px;line-height:1.6;">{html.escape(message)}</p>
      {swapped_alert_html}
      {checklist_html}
      <div style="margin-top:24px;display:flex;justify-content:center;gap:12px;flex-wrap:wrap;align-items:center;">
        <a href="/app" class="btn-primary" style="text-decoration:none;padding:10px 22px;font-size:14px;">
          &larr; Return to Workspace &amp; Re-attach Files
        </a>
        {auto_swap_btn}
      </div>
      {details_html}
    </div>
  </div>
</body>
</html>"""


def _build_embed(folder, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary) -> dict:
    """Everything the rendered page will still need after this request ends.

    On a serverless platform the next request may be served by a different,
    cold instance with an empty session table and an empty /tmp, so a page that
    links back to server-held state is a page whose download button breaks. The
    two generated files and every copilot answer therefore travel with the HTML.

    Ceiling: this inlines the workbook and CSV as base64, roughly a third larger
    than the raw bytes. At the scale this tool is used for (a few thousand
    invoices, ~250 KB encoded) that is comfortable; a client an order of
    magnitude larger would want object storage instead.
    """
    files = {}
    for kind, name, mime in (
        ("xlsx", "reconciliation.xlsx",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("csv", "findings.csv", "text/csv"),
    ):
        fpath = folder / name
        if fpath.exists():
            files[kind] = {
                "name": name,
                "mime": mime,
                "b64": base64.b64encode(fpath.read_bytes()).decode("ascii"),
            }
    return {
        "files": files,
        "copilot": precompute_copilot(tally, gstr, res, twp, gstr3b,
                                      forecast, vendors, ims_summary),
    }


def _render_finops_dashboard(token, tally, gstr, res, twp, gstr3b, forecast, vendors, ims_summary, actions,
                             embed: dict | None = None) -> str:
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
    total_files = 3 if gstr3b else 2
    total_records = len(tally) + len(gstr)
    match_pct = (len(res.pairs) / max(1, len(gstr))) * 100.0 if gstr else 100.0
    match_pct = min(100.0, max(0.0, match_pct))
    circ = 251.3
    stroke_dash = round((match_pct / 100.0) * circ, 1)
    stroke_gap = round(circ - stroke_dash, 1)
    discrepancy_count = len(claim) + len(not_in_2a) + len(mismatches) + len(conflicts)

    # --- TAB 1: Recon & Table 8 ---
    def row(label, n, value, action, pill_class):
        return (f"<tr><td><span class='tbl-strong'>{label}</span></td><td class=n>{n}</td>"
                f"<td class=n><span class='tbl-strong'>{value}</span></td>"
                f"<td><span class=\"status-pill {pill_class}\">{action}</span></td></tr>")

    recon_rows = "".join([
        row("Not in Tally (Missing Inward)", len(claim), rupees(total(claim)), "Claim before 30 Nov", "claim"),
        row("Not in 2A (Unfiled by Supplier)", len(not_in_2a), rupees(total(not_in_2a)), "Demand Section 16(2)(c) / Reverse", "reverse"),
        row("Partial Mismatch (Bill # / Amount)", len(mismatches), "&mdash;", "Review paired bills side by side", "review"),
        row("GSTIN Conflict (Multi-State PAN)", len(conflicts), rupees(total(conflicts)), "Correct branch ledger in books", "review"),
        row("Other Ledgers (Nominal Out of Scope)", len(other), rupees(total(other)), "Reconciled via non-purchase ledgers", "claim"),
    ])

    tab1_three_way = ""
    if twp is not None:
        m_rows = []
        for mp in twp.monthly:
            d_class = "delta-pos" if mp.variance_3b_2a >= 0 else "delta-neg"
            d_prefix = "+Rs " if mp.variance_3b_2a >= 0 else "-Rs "
            d_str = f"{d_prefix}{indian_number_format(abs(mp.variance_3b_2a), 2)}"
            m_rows.append(f"<tr><td><span class='tbl-strong'>{mp.month}</span></td><td class=n>Rs {indian_number_format(mp.tax_2a_by_invoice_date, 2)}</td><td class=n>Rs {indian_number_format(mp.tax_2a_by_filing_period, 2)}</td><td class=n>Rs {indian_number_format(mp.tally_tax, 2)}</td><td class=n>Rs {indian_number_format(mp.gstr3b_claimed, 2)}</td><td class=\"n {d_class}\">{d_str}</td></tr>")

        tab1_three_way = f"""
      <div class="card" style="margin-top:24px;">
        <div class="card-title">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
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
            <div class="flow-step-label" style="color:var(--trust-emerald);">3. Matched Verified</div>
            <div class="flow-step-val" style="color:var(--trust-emerald);">{rupees(twp.matched_tax)}</div>
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

        <div style="background:var(--accent-indigo-bg);border-left:4px solid var(--accent-indigo);padding:14px 18px;border-radius:0 var(--radius-xs) var(--radius-xs) 0;margin:16px 0;font-size:13px;color:var(--text-secondary);">
          <strong style="color:var(--accent-indigo);">The Honesty Caveat:</strong> GSTR-3B Table 4A includes imports, ISD, and reverse-charge credits not present in GSTR-2A B2B. So part of the <strong>{rupees(twp.gap_2a_3b)}</strong> total gap is legitimately unreconcilable from these files alone.
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
          <td><span class="tbl-strong">{html.escape(v.name[:32])}</span><br><code style="font-size:11px;color:var(--text-muted);">{v.gstin}</code></td>
          <td class="n">{rupees(v.booked_tax)}</td>
          <td class="n">{rupees(v.matched_tax)}</td>
          <td class="n" style="color:{'var(--alert-crimson)' if v.unfiled_tax > 0 else 'var(--text-muted)'};font-weight:700;">{rupees(v.unfiled_tax)}</td>
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
            <div style="font-weight:700;font-size:15px;color:var(--navy);">
              {idx}. {html.escape(ca.recipient)} ({ca.facts['invoice_count']} unfiled invoice(s))
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="seal-verified">✓ 100% Fact Verified</span>
              <button class="btn-copy" onclick="copyDraft('draft-{idx}')">Copy Notice</button>
            </div>
          </div>
          <div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px;">
            GSTIN: <code>{ca.facts['supplier_gstin']}</code> &middot; Tax at Stake: <strong style="color:var(--alert-crimson);">{rupees(ca.facts['total_tax'])}</strong>
          </div>
          <pre class="code-draft" id="draft-{idx}">{html.escape(draft_text)}</pre>
        </div>""")

    # Render Template with token replacements
    res_page = _DASHBOARD_HTML.replace("__CSS__", _CSS).replace("__MARK__", _MARK)
    embed_json = json.dumps(embed or {"files": {}, "copilot": {"topics": [], "fallback": {}}})
    res_page = res_page.replace("__EMBED_JSON__", embed_json.replace("</", "<\/"))
    res_page = res_page.replace("__TOKEN__", token)
    res_page = res_page.replace("__TOTAL_FILES__", str(total_files))
    res_page = res_page.replace("__TOTAL_RECORDS__", indian_number_format(total_records))
    res_page = res_page.replace("__ACCURACY_RATE__", f"{match_pct:.1f}%")
    res_page = res_page.replace("__DONUT_DASH__", f"{stroke_dash} {stroke_gap}")
    res_page = res_page.replace("__DISCREPANCY_COUNT__", str(discrepancy_count))
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
    res_page = res_page.replace("__CHASE_CARDS__", "".join(chase_cards) if chase_cards else '<p style="color:var(--text-muted);">No non-filing suppliers found.</p>')

    return res_page


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Milan - Autonomous GST Reconciliation Platform")
    ap.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"),
        help="Host interface to bind (default: 127.0.0.1 locally, 0.0.0.0 in cloud/container environments)",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port number to listen on (default: 8000 or $PORT)",
    )
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    display_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    try:
        print(f"\n  मिलान (Milan) is running at http://{display_host}:{args.port}")
    except UnicodeEncodeError:
        print(f"\n  Milan is running at http://{display_host}:{args.port}")
    try:
        print("  Zero cloud telemetry · 100% local.")
    except UnicodeEncodeError:
        print("  Zero cloud telemetry - 100% local.")
    print("  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopping server")


if __name__ == "__main__":
    main()
