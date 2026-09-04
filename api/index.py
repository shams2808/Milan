"""Vercel serverless entrypoint.

Vercel's Python runtime looks for one of two names in this module:

    handler  -- a BaseHTTPRequestHandler subclass   <- what Milan is
    app      -- a WSGI or ASGI application

This previously exported `app = Handler`, which handed a
BaseHTTPRequestHandler class to the runtime as though it were a WSGI
callable. The runtime would have tried to invoke it as app(environ,
start_response) and the deployment would never have served a request.
"""

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from milan.web import Handler

handler = Handler
