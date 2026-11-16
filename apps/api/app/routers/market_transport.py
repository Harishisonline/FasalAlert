"""Market (PRD §7.7, §9.2) and transport (§7.7, §9.3) endpoints."""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError
from app.models.tables import District, User
from app.security.deps import current_user, owned_field
from app.services.decision import context as ctx
from app.services.foundry.imd import highway_warning
from app.services.models import price as price_model
from app.services.models import transport as tm

router = APIRouter()


@router.get("/market/prices", tags=["market"])
def market_prices(commodity: str = Query(...), market: str = Query(...), days: int = Query(90, ge=7, le=730),
                  _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    commodity = _commodity(commodity)
    s = price_model.load_series(db, commodity, market, allow_synthetic=True)
    if not s.empty:
        s = s[s.index >= s.index.max() - pd.Timedelta(days=days)]
    series = [{"date": d.date().isoformat(), "min_rs_qtl": _f(r["min"]), "modal_rs_qtl": _f(r["modal"]), "max_rs_qtl": _f(r["max"]),
               "arrival_qtl": _f(r["arrival"]), "source": r["source"]} for d, r in s.iterrows()]
    synthetic = any(p["source"] == "synthetic_seed" for p in series)
    last = series[-1]["date"] if series else None
    return {"commodity": commodity, "market": market, "series": series, "last_date": last, "synthetic": synthetic,
            "sources": [{"label": f"AGMARKNET {market} {commodity}" if not synthetic else "Synthetic sample, not real prices",
                         "url": "https://agmarknet.gov.in" if not synthetic else None, "fetched_at": last,
                         "kind": "synthetic" if synthetic else "market", "synthetic": synthetic}]}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN -> None


@router.get("/market/forecast", tags=["market"])
def market_forecast(commodity: str = Query(...), market: str = Query(...), days: int = Query(7, ge=1, le=7),
                    _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    commodity = _commodity(commodity)
    fc = price_model.forecast(db, commodity, market, days)
    return {"commodity": commodity, "market": market, "available": fc.available, "unavailable_reason": fc.reason,
            "horizon_days": len(fc.points) if fc.available else days, "points": fc.points, "baseline": "seasonal_naive",
            "beats_baseline_pct": fc.beats_baseline_pct, "historical_range": fc.historical_range,
            "model_version": fc.model_version, "trained_at": fc.trained_at}


@router.get("/market/mandis", tags=["market"])
def market_mandis(commodity: str = Query(...), district_id: int | None = Query(default=None), field_id: int | None = Query(default=None),
                  user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    if field_id is not None:
        f = owned_field(db, user, field_id)
        lat, lon = f.lat, f.lon
    elif district_id is not None:
        d = db.get(District, district_id)
        if d is None:
            raise ApiError("not_found", "District does not exist")
        pt = db.execute(select(func.ST_Y(func.ST_GeomFromWKB(func.ST_AsBinary(District.centroid))),
                               func.ST_X(func.ST_GeomFromWKB(func.ST_AsBinary(District.centroid)))).where(District.id == district_id)).one()
        lat, lon = pt
    else:
        raise ApiError("validation_error", "district_id or field_id is required", {"field": "district_id"})
    # Accept the app's crop key as well as the AGMARKNET name: "grape" means "Grapes", "soybean" means "Soyabean"
    # (docs/UX_QA_AUDIT.md MKT-02; the web app sends the crop key).
    return ctx.nearest_markets(db, _commodity(commodity), lat, lon, limit=15)


def _commodity(value: str) -> str:
    try:
        return ctx.commodity_of(value.lower()) or value
    except (KeyError, ValueError, LookupError):
        return value


@router.get("/transport/risk", tags=["transport"])
def transport_risk(field_id: int = Query(...), days: int = Query(7, ge=1, le=7), user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    tr = ctx.transport_risk(db, f, days)
    return {"field_id": f.id, "available": tr.available, "unavailable_reason": tr.reason, "route_name": tr.route_name,
            "days": tr.days[:days], "harvest_deadline": tr.deadline.isoformat() if tr.deadline else None, "note": tm.NOTE,
            "calibrated": False, "model_version": tm.VERSION if tr.available else None, "computed_at": tr.computed_at,
            "official_warning": highway_warning(f.lat, f.lon)}


@router.get("/transport/segments", tags=["transport"])
def transport_segments(field_id: int = Query(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    mandi, segs = ctx.route_geojson(db, f)
    if not segs:
        ctx.ensure_route(db, f)
        mandi, segs = ctx.route_geojson(db, f)
    return {"field_id": f.id, "mandi": mandi, "segments": segs, "attribution": ctx.ATTRIBUTION}

