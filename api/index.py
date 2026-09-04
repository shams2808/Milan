import sys
from pathlib import Path

# Add project root to sys.path so milan module is importable
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from milan.web import Handler

# Vercel serverless entrypoint
app = Handler
