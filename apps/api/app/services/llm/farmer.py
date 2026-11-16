"""Everything FasalAlert stores about one farmer, as compact JSON for the Ask model (docs/UX_QA_AUDIT.md ASK-13).

The model may only state what is in this context, so it has to hold what the app itself shows: the account, every
field with its crop, variety, place, season start, area, stage and calibration, the latest decision and its risks, the
selected field's forecast, market and road, recent alerts and the KVK. The phone number and raw coordinates are left
out: an answer never needs them.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import iso, today_ist
from app.models.tables import AlertRow, DecisionRow, District, Field, FieldCalibration, Taluka, User, Village
from app.services.decision import engine
from app.services.decision.context import fallback_contact, kvk_for
from app.services.models import phenology

ACRE_SQM = 4046.8564224


def _r(x: Any, nd: int = 1) -> Any:
    """Rounded as the app shows it; whole numbers without ".0" so "4 ha" in an answer matches CONTEXT."""
    if not isinstance(x, float):
        return x
    y = round(x, nd)
    return int(y) if y.is_integer() else y


def _name(row: Any, loc: str) -> str | None:
    return (getattr(row, f"name_{loc}", None) or row.name_en) if row is not None else None


def _place(db: Session, f: Field, loc: str) -> dict[str, str | None]:
    return {
        "village": _name(db.get(Village, f.village_id), loc) if f.village_id else None,
        "taluka": _name(db.get(Taluka, f.taluka_id), loc) if f.taluka_id else None,
        "district": _name(db.get(District, f.district_id), loc) if f.district_id else None,
    }


def _latest_decision(db: Session, f: Field) -> DecisionRow | None:
    return db.execute(
        select(DecisionRow).where(DecisionRow.field_id == f.id).order_by(DecisionRow.decision_date.desc(), DecisionRow.id.desc()).limit(1)
    ).scalar_one_or_none()


def _stage(db: Session, f: Field, row: DecisionRow | None, loc: str, compute: bool) -> dict[str, Any] | None:
    """The stage stored with the latest decision; computed only for the selected field or a calendar crop (cheap)."""
    st: dict[str, Any] | None = (row.inputs or {}).get("stage") if row is not None else None
    fresh = row is not None and row.decision_date == today_ist()
    if not (st and st.get("stage") and fresh):
        method = phenology.crop_info(f.crop)["phenology"]["method"]
        if compute or method == "calendar":
            try:
                st = engine._stage(db, f).to_api()
            except Exception:  # noqa: BLE001 - a missing stage is stated, never guessed
                st = st or None
    if not st or not st.get("stage"):
        return None
    label = st.get("stage_label") or {}
    nxt = st.get("next_stage_label") or {}
    return {
        "now": label.get(loc) or label.get("en") or st.get("stage"),
        "next": nxt.get(loc) or nxt.get("en"),
        "next_expected_on": st.get("next_stage_expected_on"),
        "next_plus_minus_days": st.get("next_stage_plus_minus_days"),
        "method": st.get("method"),
        "explanation": (st.get("explanation") or {}).get(loc) or (st.get("explanation") or {}).get("en"),
    }


def _risk(r: dict[str, Any], loc: str) -> dict[str, Any]:
    ev = r.get("evidence") or {}
    out = {
        "kind": engine.KIND_NAMES[loc].get(r.get("kind", ""), r.get("kind")),
        "level": r.get("level"),
        "probability_percent": round((r.get("probability") or 0) * 100),
        "event_date": ev.get("event_date"),
        "window_start": r.get("window_start"),
    }
    if r.get("kind") in ("frost", "heatwave"):
        # tmin_c holds the forecast point for both kinds (the heat model reuses the field name).
        out.update({"forecast_c": _r(r.get("tmin_c")), "limit_c": _r(r.get("threshold_c")),
                    "band_c": [_r(r.get("band_low_c")), _r(r.get("band_high_c"))]})
    if r.get("kind") == "heavy_rain":
        out["forecast_rain_mm"] = _r(ev.get("forecast_rain_mm"))
    if r.get("kind") == "transport":
        out["route"] = ev.get("route_name")
    return out


def _decision(row: DecisionRow | None, loc: str, selected: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    p = row.payload or {}
    i18n = p.get("_i18n") or {}
    out: dict[str, Any] = {
        "for_date": row.decision_date.isoformat(),
        "is_today": row.decision_date == today_ist(),
        "headline": (i18n.get("headline") or {}).get(loc) or row.headline,
        "action": (i18n.get("action_text") or {}).get(loc) or row.action_text,
        "act_by": p.get("action_by"),
        "unavailable_reason": row.abstain_reason,
        "risks": [_risk(r, loc) for r in (p.get("risks") or [])[:6]],
    }
    if selected:
        m = p.get("market") or None
        if m:
            out["market"] = {k: m.get(k) for k in ("market", "commodity", "modal_rs_qtl", "price_date", "source", "distance_km",
                                                   "forecast_available", "forecast_p10", "forecast_p50", "forecast_p90") if k in m}
        t = p.get("transport") or None
        if t:
            out["road"] = {"route": t.get("route_name"), "disruption_chance_72h_percent": round((t.get("p_disruption_72h") or 0) * 100),
                           "rain_mm_72h": _r(t.get("rain_accum_mm_72h")), "load_by": t.get("harvest_deadline")}
        rec = p.get("recommendation") or None
        if rec:
            out["recommendation"] = {k: v for k, v in rec.items() if not str(k).startswith("_")}
        adv = p.get("advisory") or None
        if adv:
            out["advisory"] = adv
        out["limitations"] = p.get("limitations")
    return out


def _forecast(row: DecisionRow | None) -> list[dict[str, Any]] | None:
    """The forecast the latest decision used (dates, temperatures, rain), rounded as the app shows it."""
    fc = (row.inputs or {}).get("forecast") if row is not None else None
    if not fc:
        return None
    days = []
    for d in (fc.get("days") or [])[:7]:
        days.append({
            "date": d.get("valid_date"), "min_c": _r(d.get("tmin_c")), "max_c": _r(d.get("tmax_c")),
            "rain_mm": _r(d.get("rain_mm")),
            "rain_chance_percent": round(d["precip_prob"] * 100) if isinstance(d.get("precip_prob"), float) and d["precip_prob"] <= 1
            else d.get("precip_prob"),
            "heavy_rain_chance_percent": round(d["rain_p_heavy"] * 100) if isinstance(d.get("rain_p_heavy"), float) else None,
        })
    return [{"fetched_at": fc.get("fetched_at"), "source": "Open-Meteo (ECMWF ensemble, JMA)"}, *days] if days else None


def _calibration(db: Session, f: Field) -> dict[str, Any] | None:
    c = db.get(FieldCalibration, f.id)
    if c is None:
        return None
    return {"sensitivity": c.sensitivity, "frost_limit_c": c.frost_threshold_c, "heat_limit_c": c.heat_threshold_c,
            "reminder_lead_hours": c.harvest_lead_hours}


def _area(f: Field, unit: str) -> dict[str, Any] | None:
    if not f.area_sqm:
        return None
    return {"hectares": _r(f.area_sqm / 10_000, 2), "acres": _r(f.area_sqm / ACRE_SQM, 2), "farmer_unit": unit}


def _age(start: date | None) -> int | None:
    return (today_ist() - start).days if start else None


def farmer_context(db: Session, user: User, selected: Field | None, loc: str) -> dict[str, Any]:
    fields = db.execute(select(Field).where(Field.user_id == user.id).order_by(Field.id)).scalars().all()
    out_fields = []
    for f in fields:
        is_sel = selected is not None and f.id == selected.id
        row = _latest_decision(db, f)
        info = phenology.crop_info(f.crop)
        entry: dict[str, Any] = {
            "id": f.id,
            "name": f.name or engine.CROP_NAMES[loc][f.crop],
            "selected": is_sel,
            "crop": engine.CROP_NAMES[loc][f.crop],
            "crop_key": f.crop,
            "variety": f.variety,
            # Grapes count the season from fruit pruning, other crops from sowing or planting.
            "season_start_kind": "fruit pruning" if f.crop == "grape" else "sowing or planting",
            "season_start_date": f.sowing_date.isoformat() if f.sowing_date else None,
            "days_since_season_start": _age(f.sowing_date),
            "area": _area(f, user.area_unit),
            "place": _place(db, f, loc),
            "primary_mandi": f.primary_mandi,
            "stage": _stage(db, f, row, loc, compute=is_sel),
            "calibration": _calibration(db, f),
            "latest_decision": _decision(row, loc, is_sel),
            "added_on": f.created_at.date().isoformat() if f.created_at else None,
        }
        if is_sel:
            entry["forecast_used_by_latest_decision"] = _forecast(row)
            entry["stage_method_note"] = info["phenology"].get("method")
        out_fields.append(entry)
    alerts = db.execute(select(AlertRow).where(AlertRow.user_id == user.id).order_by(AlertRow.created_at.desc()).limit(5)).scalars().all()
    names = {f.id: (f.name or engine.CROP_NAMES[loc][f.crop]) for f in fields}
    kvk = (kvk_for(db, selected) if selected is not None else None) or fallback_contact()
    return {
        "today": today_ist().isoformat(),
        "farmer": {
            "name": user.name,
            "language": user.preferred_locale,
            "temperature_unit": user.temp_unit,
            "area_unit": user.area_unit,
            "member_since": user.created_at.date().isoformat() if user.created_at else None,
            "number_of_fields": len(fields),
        },
        "fields": out_fields,
        "recent_alerts": [{"field": names.get(a.field_id), "kind": a.kind, "level": a.level, "message": a.message,
                           "created_at": iso(a.created_at), "read": a.read_at is not None} for a in alerts],
        "kvk": kvk,
    }
