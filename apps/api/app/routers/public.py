"""Public board endpoints (PRD §7.1): no auth, 60 requests/min per IP."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError
from app.core.timeutil import iso, today_ist
from app.security.deps import public_rate_limit
from app.services.decision.public_board import compute_board, is_stale, latest_board
from app.services.foundry.http import UpstreamError

router = APIRouter(dependencies=[Depends(public_rate_limit)])

PUBLIC_KEYS = ["district_id", "code", "name", "level", "kind", "probability", "tmin_c", "tmin_at", "tmax_c", "tmax_at",
               "threshold_c", "crop", "stage", "reason"]
SOURCES = [
    {"label": "Open-Meteo forecast and ECMWF ensemble (CC BY 4.0)", "url": "https://open-meteo.com", "kind": "forecast"},
    {"label": "Crop-stage thresholds: docs/CROP_PARAMETERS.md", "url": None, "kind": "model"},
]


def _board(db: Session, day: date | None) -> tuple[list[dict[str, Any]], Any, bool]:
    rows, computed = latest_board(db, day)
    stale = is_stale(computed)
    if (not rows or (stale and (day is None or day == today_ist()))):
        try:
            compute_board(db)
            db.commit()
            rows, computed = latest_board(db, day)
            stale = is_stale(computed)
        except UpstreamError:
            stale = True  # serve the last computed board, labelled stale (PRD §7.1)
    if not rows:
        raise ApiError("data_stale", "Live data unavailable", {"last_update": None})
    return rows, computed, stale


@router.get("/public/risks", tags=["public"])
def public_risks(date_: date | None = Query(default=None, alias="date"), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows, computed, stale = _board(db, date_)
    return {"date": (date_ or today_ist()).isoformat(), "generated_at": iso(computed), "stale": stale,
            "model_version": next((r.get("model_version") for r in rows if r.get("model_version")), "frost"),
            "sources": [{**s, "fetched_at": iso(computed)} for s in SOURCES],
            "districts": [{k: r.get(k) for k in PUBLIC_KEYS} for r in rows]}


@router.get("/public/districts/{district_id}", tags=["public"])
def public_district(district_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows, computed, stale = _board(db, None)
    row = next((r for r in rows if r["district_id"] == district_id), None)
    if row is None:
        raise ApiError("not_found", "District does not exist")
    return {**{k: row.get(k) for k in PUBLIC_KEYS}, "band_low_c": row.get("band_low_c"), "band_high_c": row.get("band_high_c"),
            "affected_crops": row.get("affected_crops", []), "sources": [{**s, "fetched_at": iso(computed)} for s in SOURCES],
            "generated_at": iso(computed), "stale": stale}
