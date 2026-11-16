"""Field context assembly for the decision engine: calibration, thresholds, route risk, market summary."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import now_utc, today_ist
from app.models.tables import (
    Field,
    FieldCalibration,
    FieldRoute,
    KvkContact,
    MandiMarket,
    MandiPrice,
    RoadSegment,
    RouteRisk,
)
from app.services.foundry.http import UpstreamError, get_json
from app.services.foundry.roads import OSM_ATTRIBUTION, attach_elevation, fetch_route, haversine_km
from app.services.models import price as price_model
from app.services.models import transport as tm
from app.services.models.phenology import crop_info, stage_thresholds

log = logging.getLogger("fasalalert.decision")


def calibration(db: Session, f: Field) -> FieldCalibration:
    c = db.get(FieldCalibration, f.id)
    if c is None:
        c = FieldCalibration(field_id=f.id, sensitivity="normal", harvest_lead_hours=24)
        db.add(c)
        db.flush()
    return c


@dataclass
class Thresholds:
    frost_c: float | None
    heat_c: float | None
    frost_default: float | None
    heat_default: float | None
    source_id: str | None
    min_frost_c: float | None
    max_heat_c: float | None
    overridden: bool


def thresholds_for(crop: str, stage: str | None, cal: FieldCalibration | None) -> Thresholds:
    t = stage_thresholds(crop, stage)
    fd, hd = t.get("frost_c"), t.get("heat_c")
    fc = cal.frost_threshold_c if cal and cal.frost_threshold_c is not None else fd
    hc = cal.heat_threshold_c if cal and cal.heat_threshold_c is not None else hd
    return Thresholds(fc, hc, fd, hd, t.get("source_id"), t.get("min_frost_override_c"), t.get("max_heat_override_c"),
                      bool(cal and (cal.frost_threshold_c is not None or cal.heat_threshold_c is not None)))


def kvk_for(db: Session, f: Field) -> dict[str, str] | None:
    if f.district_id is None:
        return None
    row = db.execute(select(KvkContact).where(KvkContact.district_id == f.district_id).limit(1)).scalar_one_or_none()
    return {"name": row.name, "phone": row.phone} if row else None


def fallback_contact() -> dict[str, str]:
    return {"name": "Kisan Call Centre", "phone": get_settings().kisan_call_centre}


# ---------------- market ----------------
def commodity_of(crop: str) -> str | None:
    return crop_info(crop).get("agmarknet_commodity")


def nearest_markets(db: Session, commodity: str, lat: float, lon: float, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.execute(select(MandiMarket).where(func.lower(MandiMarket.commodity) == commodity.lower())).scalars().all()
    out = []
    for m in rows:
        dist = haversine_km((lon, lat), (m.lon, m.lat)) if m.lat is not None and m.lon is not None else None
        out.append({"id": m.id, "name": m.name, "commodity": m.commodity, "district_id": m.district_id,
                    "lat": m.lat, "lon": m.lon, "distance_km": round(dist, 1) if dist is not None else None})
    out.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))
    return out[:limit]


def market_for(db: Session, f: Field) -> tuple[str | None, str | None]:
    commodity = commodity_of(f.crop)
    if not commodity:
        return None, None
    if f.primary_mandi:
        return commodity, f.primary_mandi
    with_data = db.execute(
        select(MandiMarket.name).join(MandiPrice, MandiPrice.market_id == MandiMarket.id)
        .where(func.lower(MandiMarket.commodity) == commodity.lower()).group_by(MandiMarket.name)
    ).scalars().all()
    near = [m for m in nearest_markets(db, commodity, f.lat, f.lon, 30) if m["name"] in with_data]
    if near:
        return commodity, near[0]["name"]
    return commodity, None


def market_summary(db: Session, f: Field, p_disruption_72h: float | None) -> dict[str, Any] | None:
    commodity, market = market_for(db, f)
    if not commodity or not market:
        return None
    s = price_model.load_series(db, commodity, market, allow_synthetic=True)
    if s.empty:
        return None
    synthetic = bool((s["source"] == "synthetic_seed").any())
    recent = price_model.summarize_recent(s)
    fc = price_model.forecast(db, commodity, market)
    p10 = p50 = p90 = None
    if fc.available and fc.points:
        last = fc.points[-1]
        p10, p50, p90 = last["p10"], last["p50"], last["p90"]
    spoil = (crop_info(f.crop).get("spoilage_factor") or {}).get("value")
    loss = None
    if p50 is not None and p_disruption_72h is not None and spoil is not None:
        loss = round(p_disruption_72h * float(spoil) * p50)
    return {
        "commodity": commodity, "market": market, "modal_rs_qtl": recent["modal_rs_qtl"], "median_5d": recent["median_5d"],
        "forecast_p10": p10, "forecast_p50": p50, "forecast_p90": p90, "trend_7d_pct": recent["trend_7d_pct"],
        "baseline": "seasonal_naive", "beats_baseline_pct": fc.beats_baseline_pct, "arrival_qtl": recent["arrival_qtl"],
        "expected_transport_loss_rs_qtl": loss, "source": "synthetic_seed" if synthetic else "agmarknet",
        "price_date": recent["price_date"], "horizon_days": len(fc.points) if fc.available else None,
        "forecast_available": fc.available, "_forecast_points": fc.points, "_unavailable_reason": fc.reason,
    }


# ---------------- transport ----------------
@dataclass
class TransportResult:
    available: bool
    reason: str | None = None
    route_name: str | None = None
    days: list[dict[str, Any]] = field(default_factory=list)
    p72: float | None = None
    rain72: float | None = None
    deadline: date | None = None
    computed_at: str | None = None
    market_name: str | None = None


def _mandi_ll(db: Session, f: Field) -> tuple[str, float, float] | None:
    commodity, name = market_for(db, f)
    if not commodity:
        return None
    rows = nearest_markets(db, commodity, f.lat, f.lon, 30)
    pick = next((r for r in rows if name and r["name"] == name and r["lat"] is not None), None) or next(
        (r for r in rows if r["lat"] is not None), None)
    return (pick["name"], pick["lat"], pick["lon"]) if pick else None


def ensure_route(db: Session, f: Field, force: bool = False) -> FieldRoute | None:
    dest = _mandi_ll(db, f)
    if dest is None:
        return None
    name, mlat, mlon = dest
    existing = db.execute(select(FieldRoute).where(FieldRoute.field_id == f.id, FieldRoute.market_name == name)).scalar_one_or_none()
    if existing and not force and existing.segment_ids:
        return existing
    try:
        route = fetch_route((f.lat, f.lon), (mlat, mlon))
        attach_elevation(route)
    except (UpstreamError, ValueError) as e:
        log.warning("route for field %s unavailable: %s", f.id, e)
        return existing
    ids = []
    for seg in route.segments:
        sid = seg.synthetic_id()
        row = db.execute(select(RoadSegment).where(RoadSegment.osm_id == sid)).scalar_one_or_none()
        if row is None:
            try:
                with db.begin_nested():
                    row = RoadSegment(osm_id=sid, name=seg.name, road_class=seg.road_class, geom=from_shape(LineString(seg.coords), srid=4326),
                                      min_elev_m=seg.min_elev_m, max_elev_m=seg.max_elev_m, length_km=round(seg.length_km, 3),
                                      ref=seg.ref, source="osrm-geometry", slope_pct=seg.slope_pct, low_lying=seg.low_lying)
                    db.add(row)
                    db.flush()
            except IntegrityError:
                row = db.execute(select(RoadSegment).where(RoadSegment.osm_id == sid)).scalar_one()
        ids.append(row.id)
    try:
        # Two requests can route the same field at once (a background decision and a page): the second one's insert
        # then conflicts. Keep the route that won instead of failing the request (docs/UX_QA_AUDIT.md API-04).
        with db.begin_nested():
            if existing is None:
                existing = FieldRoute(field_id=f.id, market_name=name, source="osrm+opentopodata")
                db.add(existing)
            existing.segment_ids, existing.route_name = ids, f"{route.name} to {name}"
            existing.distance_km, existing.duration_min, existing.computed_at = round(route.distance_km, 1), round(route.duration_min), now_utc()
            db.flush()
    except IntegrityError:
        existing = db.execute(select(FieldRoute).where(FieldRoute.field_id == f.id, FieldRoute.market_name == name)
                              .execution_options(populate_existing=True)).scalar_one_or_none()
    return existing


def _rain_by_point(points: list[tuple[float, float]]) -> list[dict[date, float]]:
    s = get_settings()
    out: list[dict[date, float]] = []
    for i in range(0, len(points), 40):
        chunk = points[i:i + 40]
        data = get_json(s.open_meteo_forecast_url, {
            "latitude": ",".join(f"{p[0]:.3f}" for p in chunk), "longitude": ",".join(f"{p[1]:.3f}" for p in chunk),
            "daily": "precipitation_sum", "timezone": "Asia/Kolkata", "forecast_days": 7, "past_days": 10})
        data = data if isinstance(data, list) else [data]
        for d in data:
            dd = d["daily"]
            out.append({date.fromisoformat(t): float(v or 0.0) for t, v in zip(dd["time"], dd["precipitation_sum"], strict=False)})
    return out


def transport_risk(db: Session, f: Field, days: int = 7, store: bool = True) -> TransportResult:
    route = ensure_route(db, f)
    if route is None or not route.segment_ids:
        return TransportResult(False, "route_unknown")
    segs = db.execute(select(RoadSegment).where(RoadSegment.id.in_(route.segment_ids))).scalars().all()
    by_id = {s_.id: s_ for s_ in segs}
    ordered = [by_id[i] for i in route.segment_ids if i in by_id]
    if any(s_.min_elev_m is None for s_ in ordered):
        return TransportResult(False, "elevation_missing", route_name=route.route_name)
    mids = []
    for s_ in ordered:
        line = to_shape(s_.geom)
        mid = line.interpolate(0.5, normalized=True)
        mids.append((mid.y, mid.x))
    try:
        rains = _rain_by_point(mids)
    except UpstreamError:
        return TransportResult(False, "forecast_stale", route_name=route.route_name)
    inputs = [tm.SegmentInput(s_.id, s_.road_class, s_.slope_pct, s_.low_lying, r) for s_, r in zip(ordered, rains, strict=False)]
    day_list = [today_ist() + timedelta(days=i) for i in range(days)]
    route_days, per_seg = tm.route_risk(inputs, day_list)
    cal = calibration(db, f)
    deadline = tm.harvest_deadline(route_days, cal.harvest_lead_hours)
    if store:
        # Upsert, not delete-then-insert: two requests storing the same field's route risk at once must not collide
        # on (field_id, segment_id, valid_date) (docs/UX_QA_AUDIT.md API-04).
        keep = {(r.segment_id, r.day) for r in per_seg}
        stale = db.execute(select(RouteRisk.id, RouteRisk.segment_id, RouteRisk.valid_date)
                           .where(RouteRisk.field_id == f.id, RouteRisk.valid_date.in_(day_list))).all()
        gone = [i for i, sid, d in stale if (sid, d) not in keep]
        if gone:
            db.execute(delete(RouteRisk).where(RouteRisk.id.in_(gone)))
        if per_seg:
            stmt = pg_insert(RouteRisk).values([
                {"field_id": f.id, "segment_id": r.segment_id, "valid_date": r.day, "p_disruption": r.score,
                 "rain_accum_mm": round(r.rain_72h, 1), "model_version": tm.VERSION} for r in per_seg])
            db.execute(stmt.on_conflict_do_update(index_elements=["field_id", "segment_id", "valid_date"], set_={
                "p_disruption": stmt.excluded.p_disruption, "rain_accum_mm": stmt.excluded.rain_accum_mm,
                "model_version": stmt.excluded.model_version, "computed_at": func.now()}))
    p72 = max(rd.p_disruption for rd in route_days[:3])
    worst = max(route_days[:3], key=lambda rd: rd.p_disruption)
    rain72 = next((r.rain_72h for r in per_seg if r.day == worst.day and r.segment_id == worst.worst_segment_id), 0.0)
    return TransportResult(True, None, route.route_name,
                           [{"date": rd.day.isoformat(), "p_disruption": rd.p_disruption, "level": tm.level(rd.p_disruption),
                             "rain_mm": round(rd.rain_mm, 1)} for rd in route_days],
                           p72, round(rain72, 1), deadline, now_utc().isoformat(), route.market_name)


def route_geojson(db: Session, f: Field) -> tuple[str | None, list[dict[str, Any]]]:
    route = db.execute(select(FieldRoute).where(FieldRoute.field_id == f.id).order_by(FieldRoute.computed_at.desc())).scalars().first()
    if route is None:
        return None, []
    segs = db.execute(select(RoadSegment).where(RoadSegment.id.in_(route.segment_ids))).scalars().all()
    by_id = {s_.id: s_ for s_ in segs}
    out = []
    for i in route.segment_ids:
        s_ = by_id.get(i)
        if s_ is None:
            continue
        out.append({"id": s_.id, "name": s_.name or s_.ref, "road_class": s_.road_class, "length_km": s_.length_km,
                    "min_elev_m": s_.min_elev_m, "max_elev_m": s_.max_elev_m,
                    "coordinates": [list(c) for c in to_shape(s_.geom).coords]})
    return route.market_name, out


ATTRIBUTION = OSM_ATTRIBUTION
