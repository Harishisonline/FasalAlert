"""Train and backtest every commodity-market series with real history (PRD §9.2). Usage: uv run python scripts/train_prices.py"""
import json

import _bootstrap  # noqa: F401

from app.core.db import session_scope
from app.services.models.price import train_all

with session_scope() as db:
    print(json.dumps(train_all(db), indent=1))
