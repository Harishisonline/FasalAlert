"""Public district risk board (PRD §7.1): the same frost/heat classifier that serves farmers, run at each
district centroid for every tracked crop at its typical stage this season. Nothing here is mocked.
A district with no forecast is 'nodata' and excluded from the ranking.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import IST, iso, now_ist, now_utc, today_ist
from app.models.tables import District, PublicDistrictRisk
from app.services.decision import policy
from app.services.decision.engine import CROP_NAMES, _predict
from app.services.foundry.climate import daily_history
from app.services.foundry.http import UpstreamError, get_json
from app.services.models import phenology
from app.services.models.frost_interface import FrostFeatures

log = logging.getLogger("fasalalert.public")
DISTRICT_NAME_MR = "name_mr"


def _season_start(info: dict[str, Any], today: date) -> date | None:
    md = (info.get("sowing_defaults") or {}).get("month_day")
    if not md:
        return None
    m, d = (int(x) for x in md.split("-"))
    start = date(today.year, m, d)
    return start if start <= today else date(today.year - 1, m, d)


def crop_stages_for_point(db: Session, lat: float, lon: float, today: date) -> dict[str, phenology.StageResult]:
    out = {}
    for crop, info in phenology.crop_table()["crops"].items():
        method = info["phenology"]["method"]
        try:
            if method == "calendar":
                out[crop] = phenology.compute_stage(crop, None, today=today)
                continue
            start = _season_start(info, today)
            if start is None:
                continue
            daily = None
            if method == "gdd":
                hist = daily_history(db, lat, lon, start)
                daily = [(h.day, h.tmin_c, h.tmax_c) for h in hist]
            st = phenology.compute_stage(crop, start, daily, today=today)
            gone = (st.gdd_cum if method == "gdd" else (today - start).days) > phenology.season_length(crop)
            if st.stage and not gone:
                out[crop] = st
        except (KeyError, ValueError, LookupError, UpstreamError) as e:
            log.debug("stage for %s at %.2f,%.2f unavailable: %s", crop, lat, lon, e)
    return out


def _multi_forecast(points: list[tuple[float, float]]) -> list[dict[str, Any] | None]:
    s = get_settings()
    lat = ",".join(f"{p[0]:.3f}" for p in points)
    lon = ",".join(f"{p[1]:.3f}" for p in points)
    # The deterministic forecast is required: without it there is no board at all, so it keeps the
    # retry budget. The ensemble and JMA calls only add a spread band and the JMA input, and they
    # degrade to None, so they fail fast rather than spending the function's time on a 429.
    det = get_json(s.open_meteo_forecast_url, {"latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata", "forecast_days": 3,
                                               "daily": "temperature_2m_min,temperature_2m_max", "hourly": "temperature_2m"}, timeout=60)
    det = det if isinstance(det, list) else [det]
    try:
        ens = get_json(s.open_meteo_ensemble_url, {"latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata", "forecast_days": 3,
                                                   "daily": "temperature_2m_min,temperature_2m_max", "models": "ecmwf_ifs025"}, timeout=90,
                       attempts=1, wait_budget=0)
        ens = ens if isinstance(ens, list) else [ens]
    except UpstreamError:
        ens = [None] * len(points)
    try:  # the classifier was trained on JMA forecasts (docs/model_cards/frost.md)
        jma = get_json(s.open_meteo_forecast_url, {"latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata", "forecast_days": 3,
                                                   "daily": "temperature_2m_min,temperature_2m_max", "models": "jma_seamless"}, timeout=60,
                       attempts=1, wait_budget=0)
        jma = jma if isinstance(jma, list) else [jma]
    except UpstreamError:
        jma = [None] * len(points)
    return [{"det": d, "ens": e, "jma": j, "elevation": d.get("elevation")} for d, e, j in zip(det, ens, jma, strict=False)]


def _jma_value(fc: dict[str, Any], var: str, day: str) -> float | None:
    daily = (fc.get("jma") or {}).get("daily", {})
    times = daily.get("time", [])
    return daily[var][times.index(day)] if day in times and daily.get(var) else None


def _event_at(hourly: dict[str, Any], kind: str, day: str) -> datetime:
    """Hour of the day's minimum (frost: 00:00 to 09:00) or maximum (heat), IST."""
    hrs = [(t, v) for t, v in zip(hourly.get("time", []), hourly.get("temperature_2m", []), strict=False) if t.startswith(day) and v is not None]
    pick = (min if kind == "frost" else max)([h for h in hrs if (int(h[0][11:13]) <= 9) == (kind == "frost")] or hrs, key=lambda h: h[1]) if hrs else None
    return datetime.fromisoformat(pick[0]).replace(tzinfo=IST) if pick else datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=IST)


def _spread(ens: dict[str, Any] | None, var: str, i: int) -> float | None:
    if not ens:
        return None
    daily = ens.get("daily", {})
    vals = [daily[k][i] for k in daily if k.startswith(var + "_member") and daily[k][i] is not None]
    if len(vals) < 10:
        return None
    m = sum(vals) / len(vals)
    return round((sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5, 2)


def _when(at: datetime, loc: str, kind: str = "frost") -> str:
    today = today_ist()
    local = at.astimezone(IST)
    d = local.date()
    if kind == "frost" and (d == today or (d == today + timedelta(days=1) and local.hour < 9)):
        return {"en": "tonight", "mr": "आज रात्री", "hi": "आज रात"}[loc]
    if kind != "frost" and d == today:   # a heat peak falls in the afternoon
        return {"en": "today", "mr": "आज", "hi": "आज"}[loc]
    return {"en": f"on {at:%a %d %b}", "mr": f"{at:%d/%m} रोजी", "hi": f"{at:%d/%m} को"}[loc]


def compute_board(db: Session) -> list[dict[str, Any]]:
    today = today_ist()
    districts = db.execute(select(District).order_by(District.name_en)).scalars().all()
    pts = []
    for d in districts:
        p = to_shape(d.centroid)
        pts.append((p.y, p.x))
    fcs: list[dict[str, Any] | None] = []
    for i in range(0, len(pts), 40):
        try:
            fcs += _multi_forecast(pts[i:i + 40])
        except UpstreamError as e:
            # A failed refresh must not replace the last good board with empty rows: the caller
            # serves the previous board, labelled stale (PRD §7.1). Found in production on
            # 2026-11-17, when Open-Meteo answered 429 and every district became 'nodata'.
            log.warning("district forecasts unavailable: %s", e)
            raise
    fetched = now_utc()
    rows = []
    for d, (lat, lon), fc in zip(districts, pts, fcs, strict=False):
        name = {"en": d.name_en, "mr": d.name_mr, "hi": d.name_hi}
        base = {"district_id": d.id, "code": d.code, "name": name}
        if fc is None:
            rows.append({**base, "level": "nodata", "kind": None, "probability": None, "tmin_c": None, "tmin_at": None,
                         "tmax_c": None, "tmax_at": None, "threshold_c": None, "crop": None, "stage": None, "reason": None,
                         "band_low_c": None, "band_high_c": None, "affected_crops": []})
            continue
        det = fc["det"]["daily"]
        hourly = fc["det"].get("hourly", {})
        stages = crop_stages_for_point(db, lat, lon, today)
        best = None
        affected = []
        # only days whose event hour is still ahead: this morning's minimum has already happened
        ahead = {k: [i for i in range(len(det["time"])) if _event_at(hourly, k, det["time"][i]) > fetched] or list(range(len(det["time"])))
                 for k in ("frost", "heat")}
        tmin_day = min(ahead["frost"], key=lambda i: det["temperature_2m_min"][i])
        tmax_day = max(ahead["heat"], key=lambda i: det["temperature_2m_max"][i])
        times = {"frost": _event_at(hourly, "frost", det["time"][tmin_day]), "heat": _event_at(hourly, "heat", det["time"][tmax_day])}
        for crop, st in stages.items():
            th = phenology.stage_thresholds(crop, st.stage)
            for kind, thr_key, var, idx in (("frost", "frost_c", "temperature_2m_min", tmin_day), ("heat", "heat_c", "temperature_2m_max", tmax_day)):
                thr = th.get(thr_key)
                if thr is None:
                    continue
                at = times[kind]
                lead = max(0, int((at - fetched).total_seconds() // 3600))
                jv = _jma_value(fc, var, det["time"][idx])
                pred = _predict(FrostFeatures(kind=kind, lat=lat, lon=lon, valid_date=at.date(), lead_hours=lead, threshold_c=float(thr),
                                              forecast_c=float(jv if jv is not None else det[var][idx]), ensemble_spread_c=_spread(fc["ens"], var, idx),
                                              elevation_m=fc["elevation"]))
                lvl = policy.level_for(pred.probability, lead)
                k = "frost" if kind == "frost" else "heatwave"
                if lvl != "none":
                    affected.append({"crop": crop, "stage": st.stage, "kind": k, "threshold_c": float(thr), "level": lvl})
                cand = (policy.rank(lvl), pred.probability, crop, st, k, float(thr), pred, at)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        tmin, tmax = det["temperature_2m_min"][tmin_day], det["temperature_2m_max"][tmax_day]
        row = {**base, "tmin_c": tmin, "tmin_at": iso(times["frost"]), "tmax_c": tmax, "tmax_at": iso(times["heat"]),
               "affected_crops": affected, "band_low_c": None, "band_high_c": None}
        if best is None:
            row.update({"level": "none", "kind": None, "probability": None, "threshold_c": None, "crop": None, "stage": None,
                        "reason": {"en": f"{d.name_en}: no tracked crop has a frost or heat threshold at its current stage.",
                                   "mr": f"{d.name_mr}: सध्याच्या अवस्थेत कोणत्याही पिकाची दंव किंवा उष्णता मर्यादा नाही.",
                                   "hi": f"{d.name_hi}: मौजूदा अवस्था में किसी फसल की पाला या गर्मी सीमा नहीं है."}})
        else:
            lvl_rank, p, crop, st, k, thr, pred, at = best
            val = pred.point_c   # the model's corrected estimate, not the raw forecast shown as tmin_c / tmax_c
            below = val < thr     # state the actual relation, whatever the level
            stage_lbl = st.stage_label or {"en": st.stage, "mr": st.stage, "hi": st.stage}
            reason = {}
            for loc in ("en", "mr", "hi"):
                rel = {"en": "below" if below else "above", "mr": "पेक्षा कमी" if below else "पेक्षा जास्त",
                       "hi": "से कम" if below else "से ज़्यादा"}[loc]
                name_l = name[loc]
                if loc == "en":
                    reason[loc] = (f"{name_l}: estimated {val:.1f} °C {_when(at, loc, k)} (forecast after error correction), {rel} the {thr:g} °C "
                                   f"{stage_lbl['en'].lower()} threshold for {CROP_NAMES['en'][crop]}.")
                elif loc == "mr":
                    reason[loc] = (f"{name_l}: {_when(at, loc, k)} सुधारित अंदाज {val:.1f} °C, {CROP_NAMES['mr'][crop]} "
                                   f"{stage_lbl['mr']} मर्यादा {thr:g} °C {rel}.")
                else:
                    reason[loc] = (f"{name_l}: {_when(at, loc, k)} सुधारा हुआ अनुमान {val:.1f} °C, {CROP_NAMES['hi'][crop]} "
                                   f"{stage_lbl['hi']} सीमा {thr:g} °C {rel}.")
            row.update({"level": policy.LEVELS[lvl_rank], "kind": k, "probability": round(p, 3), "threshold_c": thr,
                        "crop": crop, "stage": st.stage, "reason": reason,
                        "band_low_c": pred.band_low_c, "band_high_c": pred.band_high_c, "model_version": pred.model_version,
                        "method": pred.method})
        rows.append(row)
    for row in rows:
        stmt = insert(PublicDistrictRisk).values(district_id=row["district_id"], risk_date=today, payload={**row, "generated_at": iso(fetched)},
                                                 model_version=row.get("model_version") or "frost")
        stmt = stmt.on_conflict_do_update(index_elements=["district_id", "risk_date"],
                                          set_={"payload": stmt.excluded.payload, "model_version": stmt.excluded.model_version,
                                                "computed_at": now_utc()})
        db.execute(stmt)
    db.flush()
    return rows


def latest_board(db: Session, day: date | None = None) -> tuple[list[dict[str, Any]], datetime | None]:
    """The most recent board that carries data.

    A board whose districts are all 'nodata' means the upstream weather fetch failed: it is skipped
    so the previous good board is served instead (found in production on 2026-11-17).
    """
    day = day or today_ist()
    rows = db.execute(select(PublicDistrictRisk).where(PublicDistrictRisk.risk_date <= day)
                      .order_by(PublicDistrictRisk.risk_date.desc(), PublicDistrictRisk.computed_at.desc())).scalars().all()
    if not rows:
        return [], None
    for latest_date in sorted({r.risk_date for r in rows}, reverse=True):
        use = [r for r in rows if r.risk_date == latest_date]
        if any(r.payload.get("level") != "nodata" for r in use):
            return [r.payload for r in use], max(r.computed_at for r in use)
    return [], None


def is_stale(computed_at: datetime | None) -> bool:
    return computed_at is None or now_ist() - computed_at.astimezone(IST) > policy.FORECAST_STALE_AFTER
