"""Vercel serverless entrypoint.

Vercel's Python runtime scans this file for a top-level `handler`, `app` or
`application`. That scan is static -- it reads the AST rather than importing
the module -- so the symbol has to be *defined* here, not aliased in.

    handler = Handler          <- valid Python, NOT detected: it is an
                                  assignment whose value is an imported name
    class handler(Handler)     <- detected, and the shape Vercel documents

An earlier version exported `app = Handler`, which was wrong twice over: the
name `app` means a WSGI/ASGI callable, and Milan is a BaseHTTPRequestHandler.
Then `handler = Handler` fixed the name but kept the undetectable shape and
failed the build with "Could not find a top-level app, application, or
handler in api/index.py".

Subclassing adds no behaviour -- every route, header and upload limit comes
from milan.web.Handler.
"""

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from milan.web import Handler


class handler(Handler):  # noqa: N801 - Vercel requires this exact name
    pass
