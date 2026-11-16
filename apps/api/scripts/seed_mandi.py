"""PRD §10.1: optional SYNTHETIC price history so the market UI is not empty on a fresh development box.

Every row has source='synthetic_seed'; the API labels it "Sample data" and the price model never trains
on it. Refused in production. Usage:
    uv run python scripts/seed_mandi.py --market Pune --commodity Mango --days 90 --i-understand-this-is-synthetic
"""
import argparse
from datetime import timedelta

import _bootstrap  # noqa: F401
import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.timeutil import today_ist
from app.models.tables import MandiMarket, MandiPrice

ap = argparse.ArgumentParser()
ap.add_argument("--market", required=True)
ap.add_argument("--commodity", required=True)
ap.add_argument("--days", type=int, default=90)
ap.add_argument("--base", type=float, required=True, help="starting modal price in Rs/qtl (you choose it; it is not data)")
ap.add_argument("--i-understand-this-is-synthetic", action="store_true", dest="ack")
a = ap.parse_args()
if get_settings().is_production:
    raise SystemExit("refused: synthetic seed data is never written in production")
if not a.ack:
    raise SystemExit("refused: pass --i-understand-this-is-synthetic")
rng = np.random.default_rng(42)
with session_scope() as db:
    m = db.execute(select(MandiMarket).where(MandiMarket.name == a.market, MandiMarket.commodity == a.commodity)).scalar_one_or_none()
    if m is None:
        m = MandiMarket(name=a.market, commodity=a.commodity)
        db.add(m)
        db.flush()
    price = a.base
    for i in range(a.days, 0, -1):
        d = today_ist() - timedelta(days=i)
        price *= float(np.exp(rng.normal(0, 0.01)))
        db.execute(insert(MandiPrice).values(market_id=m.id, commodity=a.commodity, price_date=d, modal_rs_qtl=round(price),
                                             min_rs_qtl=round(price * 0.9), max_rs_qtl=round(price * 1.1),
                                             arrival_qtl=round(float(rng.uniform(400, 1200))), source="synthetic_seed",
                                             source_url=None, licence="synthetic, not data", quality="suspect")
                   .on_conflict_do_nothing(index_elements=["market_id", "commodity", "price_date"]))
    print(f"wrote up to {a.days} SYNTHETIC rows for {a.commodity} at {a.market} (source=synthetic_seed)")
