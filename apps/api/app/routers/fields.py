"""Fields, phenology, calibration, decisions, risks, weather (PRD §7.3, §7.4, §7.10, §11)."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.errors import ApiError
from app.core.timeutil import iso, today_ist
from app.models.tables import (
    AlertRow,
    DecisionRow,
    District,
    Field,
    RiskRow,
    Taluka,
    User,
    Village,
    WeatherObservation,
)
from app.schemas.bodies import CalibrationPatchBody, FieldCreateBody, FieldPatchBody
from app.security.deps import audit, current_user, owned_field
from app.services.decision import engine
from app.services.decision.context import calibration, thresholds_for
from app.services.decision.policy import HORIZON_HOURS
from app.services.foundry.http import UpstreamError
from app.services.foundry.openmeteo import get_forecast, latest_stored
from app.services.models import phenology

router = APIRouter()

PRD_DECISION_KEYS = ["field_id", "decision_date", "headline", "action_text", "action_by", "confidence", "abstain_reason",
                     "risks", "market", "transport", "recommendation", "advisory", "sources", "model_versions"]
PRD_ABSTAIN_KEYS = ["field_id", "decision_date", "headline", "action_text", "confidence", "abstain_reason", "risks", "kvk"]
PRD_RISK_KEYS = ["kind", "level", "probability", "tmin_c", "band_low_c", "band_high_c", "threshold_c", "window_start",
                 "window_end", "lead_hours", "model_version", "evidence"]
PRD_MARKET_KEYS = ["commodity", "market", "modal_rs_qtl", "median_5d", "forecast_p10", "forecast_p50", "forecast_p90",
                   "trend_7d_pct", "baseline", "beats_baseline_pct", "arrival_qtl", "expected_transport_loss_rs_qtl", "source"]


def locale_of(user: User, accept_language: str | None, locale: str | None) -> str:
    for cand in (locale, (accept_language or "").split(",")[0][:2], user.preferred_locale):
        if cand in ("en", "mr", "hi"):
            return cand
    return "mr"


def prd_shape(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """Exact PRD §11.1 / §11.2 shape (AC 12): only PRD keys, in PRD order."""
    p = engine.localize(payload, locale)
    if p.get("abstain_reason"):
        out = {k: p.get(k) for k in PRD_ABSTAIN_KEYS}
        out["confidence"] = 0.0
        out["risks"] = [{k: r.get(k) for k in PRD_RISK_KEYS if k in r} for r in p.get("risks", [])]
        return out
    out = {k: p.get(k) for k in PRD_DECISION_KEYS}
    out["risks"] = [{k: r.get(k) for k in PRD_RISK_KEYS if k in r} for r in p.get("risks", [])]
    if out["market"]:
        out["market"] = {k: out["market"].get(k) for k in PRD_MARKET_KEYS}
    return out


def _location_label(db: Session, f: Field) -> dict[str, str] | None:
    parts = []
    for model, fid in ((Village, f.village_id), (Taluka, f.taluka_id), (District, f.district_id)):
        if fid:
            row = db.get(model, fid)
            if row:
                parts.append(row)
    if not parts:
        return None
    return {loc: ", ".join(getattr(p, f"name_{loc}") for p in parts) for loc in ("en", "mr", "hi")}


STAGE_PENDING = {"en": "Being worked out with today's decision.", "mr": "आजच्या निर्णयासोबत ठरवली जात आहे.",
                 "hi": "आज के निर्णय के साथ तय की जा रही है।"}


def stage_for(db: Session, f: Field, compute_gdd: bool = True) -> dict[str, Any]:
    try:
        if not compute_gdd and phenology.crop_info(f.crop)["phenology"]["method"] == "gdd":
            last = engine.latest(db, f.id)
            if last and last.inputs.get("stage"):
                return last.inputs["stage"]
            # Lists never fetch weather history inline: that wrote rows a background decision could hold locked
            # for its whole run and stalled every request (docs/UX_QA_AUDIT.md API-03). The decision fills it in.
            pending = phenology.unknown_stage(f.crop).to_api()
            pending["explanation"] = STAGE_PENDING
            return pending
        return engine._stage(db, f).to_api()
    except (KeyError, ValueError, LookupError):
        return phenology.unknown_stage(f.crop).to_api()


def serialize_field(db: Session, f: Field, compute_gdd: bool = False) -> dict[str, Any]:
    return {"id": f.id, "name": f.name, "crop": f.crop, "variety": f.variety,
            "sowing_date": f.sowing_date.isoformat() if f.sowing_date else None, "lat": f.lat, "lon": f.lon,
            "area_sqm": f.area_sqm, "village_id": f.village_id, "taluka_id": f.taluka_id, "district_id": f.district_id,
            "primary_mandi": f.primary_mandi, "location_label": _location_label(db, f), "stage": stage_for(db, f, compute_gdd)}


# Fields whose decision is being recomputed in a background task of this process. /decisions/today does not
# compute them a second time in parallel (docs/UX_QA_AUDIT.md HOME-02); the web app shows them as pending.
PENDING_RECOMPUTE: set[int] = set()


def _schedule_recompute(bg: BackgroundTasks, field_id: int) -> None:
    PENDING_RECOMPUTE.add(field_id)
    bg.add_task(_recompute_later, field_id)


def _recompute_later(field_id: int) -> None:
    db = SessionLocal()
    try:
        f = db.get(Field, field_id)
        if f:
            engine.compute(db, f)
            db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("fasalalert.decision").exception("recompute failed for field %s", field_id)
    finally:
        PENDING_RECOMPUTE.discard(field_id)
        db.close()


@router.get("/fields", tags=["fields"])
def list_fields(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(Field).where(Field.user_id == user.id).order_by(Field.id)).scalars()
    return [serialize_field(db, f) for f in rows]


@router.post("/fields", tags=["fields"], status_code=201)
def create_field(body: FieldCreateBody, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    n = len(db.execute(select(Field.id).where(Field.user_id == user.id)).all()) + 1
    name = body.name or {"en": f"{body.crop.capitalize()} field {n}", "mr": f"{engine.CROP_NAMES['mr'][body.crop]} शेत {n}",
                         "hi": f"{engine.CROP_NAMES['hi'][body.crop]} खेत {n}"}[user.preferred_locale]
    if body.village_id and not body.taluka_id:
        v = db.get(Village, body.village_id)
        body.taluka_id = v.taluka_id if v else None
    if body.taluka_id and not body.district_id:
        t = db.get(Taluka, body.taluka_id)
        body.district_id = t.district_id if t else None
    f = Field(user_id=user.id, name=name, **body.model_dump(exclude={"name"}))
    db.add(f)
    db.flush()
    calibration(db, f)
    audit(db, user.id, "field_create", "field", str(f.id))
    db.commit()
    _schedule_recompute(bg, f.id)  # PRD §7.8: first decision is computed after save
    return serialize_field(db, f)


@router.get("/fields/{field_id}", tags=["fields"])
def get_field(field_id: int, accept_language: str | None = Header(default=None), locale: str | None = Query(default=None),
              user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    loc = locale_of(user, accept_language, locale)
    last = engine.latest(db, f.id)
    risks = db.execute(select(RiskRow).where(RiskRow.field_id == f.id).order_by(RiskRow.computed_at.desc()).limit(10)).scalars().all()
    payload = last.payload if last else None
    return {**serialize_field(db, f, compute_gdd=True),
            "risks": (payload or {}).get("risks", []) if payload else [_risk_row(r) for r in risks],
            "last_decision": engine.localize(payload, loc) if payload else None,
            "limitations": (payload or {}).get("limitations", [])}


def _risk_row(r: RiskRow) -> dict[str, Any]:
    return {"kind": r.kind, "level": r.level, "probability": r.probability, "band_low_c": r.tmin_band_low,
            "band_high_c": r.tmin_band_high, "threshold_c": r.threshold_c, "window_start": iso(r.window_start),
            "window_end": iso(r.window_end), "lead_hours": r.lead_hours, "model_version": r.model_version, "evidence": r.evidence}


@router.patch("/fields/{field_id}", tags=["fields"])
def patch_field(field_id: int, body: FieldPatchBody, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(f, k, v)
    audit(db, user.id, "field_update", "field", str(f.id), fields=sorted(data))
    db.commit()
    _schedule_recompute(bg, f.id)  # PRD §7.4: next decision recomputed
    return serialize_field(db, f)


@router.delete("/fields/{field_id}", tags=["fields"], status_code=204, summary="ADDITIVE: delete a field and its history")
def delete_field(field_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    f = owned_field(db, user, field_id)   # another user's field is a 404, never a 403
    audit(db, user.id, "field_delete", "field", str(f.id))
    db.delete(f)   # decisions, risks, alerts, calibration and route rows cascade in the database (ON DELETE CASCADE)
    db.commit()
    return Response(status_code=204)


@router.get("/fields/{field_id}/decisions", tags=["fields"])
def field_decisions(field_id: int, days: int = Query(30, ge=1, le=90), locale: str | None = Query(default=None),
                    user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    f = owned_field(db, user, field_id)
    loc = locale or user.preferred_locale
    since = today_ist() - timedelta(days=days)
    rows = db.execute(select(DecisionRow).where(DecisionRow.field_id == f.id, DecisionRow.decision_date >= since)
                      .order_by(DecisionRow.decision_date.desc())).scalars().all()
    out = []
    for d in rows:
        alerts = db.execute(select(AlertRow).where(AlertRow.decision_id == d.id)).scalars().all()
        out.append({"decision": prd_shape(d.payload, loc), "outcome": _outcome(db, f, d),
                    "alerts": [{"id": a.id, "kind": a.kind, "level": a.level, "message": a.message, "feedback": a.feedback} for a in alerts]})
    return out


def _outcome(db: Session, f: Field, d: DecisionRow) -> dict[str, Any]:
    """Confirm a past frost/heat call against later reanalysis (labelled as reanalysis, not station data)."""
    risk = next((r for r in d.payload.get("risks", []) if r["kind"] in ("frost", "heatwave")), None)
    if not risk:
        return {"status": "pending"}
    ev_date = risk.get("evidence", {}).get("event_date")
    if not ev_date:
        return {"status": "pending"}
    key = f"g{round(f.lat, 1):.1f}_{round(f.lon, 1):.1f}"
    # event_date is stored as an ISO string in the payload; compare it as a date (docs/UX_QA_AUDIT.md API-05).
    obs = db.execute(select(WeatherObservation).where(WeatherObservation.station_id == key,
                                                      WeatherObservation.obs_date == date.fromisoformat(ev_date))).scalars().first()
    if obs is None or obs.tmin_c is None:
        return {"status": "pending"}
    val = obs.tmin_c if risk["kind"] == "frost" else obs.tmax_c
    thr = risk.get("threshold_c")
    happened = (val < thr) if risk["kind"] == "frost" else (val > thr)
    return {"status": "confirmed" if happened else "did_not_happen", "observed_value_c": val,
            "source": "ERA5 reanalysis (Open-Meteo archive)", "observed_on": ev_date}


@router.get("/fields/{field_id}/calibration", tags=["fields"])
def get_calibration(field_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    return _cal_out(db, f)


def _cal_out(db: Session, f: Field) -> dict[str, Any]:
    c = calibration(db, f)
    st = stage_for(db, f, compute_gdd=False)
    th = thresholds_for(f.crop, st.get("stage"), None)
    src = phenology.source_for(th.source_id)
    return {"field_id": f.id, "sensitivity": c.sensitivity, "frost_threshold_c": c.frost_threshold_c,
            "heat_threshold_c": c.heat_threshold_c, "harvest_lead_hours": c.harvest_lead_hours,
            "defaults": {"frost_threshold_c": th.frost_default, "heat_threshold_c": th.heat_default,
                         "source": (src or {}).get("title") or (src or {}).get("institution") or "crop table",
                         "min_frost_c": th.min_frost_c, "max_heat_c": th.max_heat_c},
            "lead_hours_by_sensitivity": HORIZON_HOURS}


@router.patch("/fields/{field_id}/calibration", tags=["fields"])
def patch_calibration(field_id: int, body: CalibrationPatchBody, bg: BackgroundTasks, user: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    c = calibration(db, f)
    st = stage_for(db, f, compute_gdd=False)
    th = thresholds_for(f.crop, st.get("stage"), None)
    data = body.model_dump(exclude_unset=True)
    fr = data.get("frost_threshold_c")
    if fr is not None and th.min_frost_c is not None and fr < th.min_frost_c:
        raise ApiError("validation_error", f"Cannot be lower than {th.min_frost_c} °C for this crop stage",
                       {"field": "frost_threshold_c", "icar_value": th.frost_default, "limit": th.min_frost_c})
    hr = data.get("heat_threshold_c")
    if hr is not None and th.max_heat_c is not None and hr > th.max_heat_c:
        raise ApiError("validation_error", f"Cannot be higher than {th.max_heat_c} °C for this crop stage",
                       {"field": "heat_threshold_c", "icar_value": th.heat_default, "limit": th.max_heat_c})
    for k, v in data.items():
        setattr(c, k, v)
    audit(db, user.id, "calibration_update", "field", str(f.id), fields=sorted(data))
    db.commit()
    bg.add_task(_recompute_later, f.id)
    return _cal_out(db, f)


@router.get("/decisions/today", tags=["decisions"])
def decisions_today(accept_language: str | None = Header(default=None), locale: str | None = Query(default=None),
                    user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    loc = locale_of(user, accept_language, locale)
    out, failed = [], []
    for f in db.execute(select(Field).where(Field.user_id == user.id).order_by(Field.id)).scalars().all():
        row = db.execute(select(DecisionRow).where(DecisionRow.field_id == f.id, DecisionRow.decision_date == today_ist())).scalar_one_or_none()
        if row:
            out.append(prd_shape(row.payload, loc))
            continue
        if f.id in PENDING_RECOMPUTE:
            continue  # being worked out right now; listed as pending by the client instead of computed twice
        try:
            with db.begin_nested():
                out.append(prd_shape(engine.compute(db, f), loc))
        except Exception:  # noqa: BLE001 - PRD §13: a failed engine is model_unavailable, never a stack trace
            logging.getLogger("fasalalert.decision").exception("decision failed for field %s", f.id)
            failed.append(f.id)
    if failed and not out:
        raise ApiError("model_unavailable", "Recommendations are unavailable right now", {"field_ids": failed})
    return out


@router.get("/risks/active", tags=["decisions"])
def risks_active(field_id: int = Query(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    f = owned_field(db, user, field_id)
    last = engine.latest(db, f.id)
    if last and last.decision_date == today_ist():
        return [{k: r.get(k) for k in PRD_RISK_KEYS if k in r} for r in last.payload.get("risks", [])]
    try:
        with db.begin_nested():
            return [{k: r.get(k) for k in PRD_RISK_KEYS if k in r} for r in engine.compute(db, f).get("risks", [])]
    except Exception:  # noqa: BLE001 - this endpoint is the fallback when the engine is down (PRD §7.3)
        logging.getLogger("fasalalert.decision").exception("risks for field %s", f.id)
    rows = db.execute(select(RiskRow).where(RiskRow.field_id == f.id).order_by(RiskRow.computed_at.desc()).limit(10)).scalars().all()
    if not rows:
        raise ApiError("model_unavailable", "Risk models are unavailable right now", {"field_id": f.id})
    return [_risk_row(r) for r in rows]


@router.get("/weather/forecast", tags=["weather"])
def weather_forecast(field_id: int = Query(...), days: int = Query(7, ge=1, le=7), user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    f = owned_field(db, user, field_id)
    stale = False
    try:
        get_forecast(db, f.lat, f.lon, field_id=f.id)
    except UpstreamError:
        stale = True
    rows = latest_stored(db, f.id)
    if not rows:
        raise ApiError("data_stale", "Forecast unavailable", {"source": "open-meteo"})
    return {"field_id": f.id, "stale": stale, "rows": [
        {"valid_date": r.valid_date.isoformat(), "tmin_c": r.tmin_c, "tmax_c": r.tmax_c, "rain_mm": r.rain_mm,
         "precip_prob": r.precip_prob, "issued_at": iso(r.issued_at), "lead_hours": r.lead_hours, "source": r.source,
         "fetched_at": iso(r.fetched_at)} for r in rows[:days]],
        "source": {"label": "Open-Meteo forecast (CC BY 4.0)", "url": "https://open-meteo.com", "fetched_at": iso(rows[0].fetched_at), "kind": "forecast"}}
