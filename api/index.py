"""Vercel Python function entry point for the FasalAlert API.

The deployed bundle keeps the repository layout, so `apps/api` is the import
root and `app.*` resolves exactly as it does locally (apps/api/app/main.py).
Vercel serves the exported ASGI app on every path, which is why the routing
entry in vercel.json sends everything to this file.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API_ROOT = os.path.join(_ROOT, "apps", "api")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

from app.main import app  # noqa: E402  (import path is set up above)

__all__ = ["app"]
