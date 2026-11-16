"""Make `app` importable when scripts run as `uv run python scripts/x.py` from apps/api."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
