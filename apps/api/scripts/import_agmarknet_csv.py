"""Import an official AGMARKNET report export (CSV). Provenance is mandatory.
Usage: uv run python scripts/import_agmarknet_csv.py FILE.csv --source-url URL --retrieved-at 2026-11-02T10:00:00+05:30
"""
import argparse
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from app.core.db import session_scope
from app.services.foundry.agmarknet import import_csv

ap = argparse.ArgumentParser()
ap.add_argument("file", type=Path)
ap.add_argument("--source-url", required=True)
ap.add_argument("--retrieved-at", required=True)
ap.add_argument("--all-states", action="store_true")
a = ap.parse_args()
with session_scope() as db:
    n = import_csv(db, a.file, a.source_url, datetime.fromisoformat(a.retrieved_at), None if a.all_states else "Maharashtra")
print(f"imported {n} rows from {a.file}")
