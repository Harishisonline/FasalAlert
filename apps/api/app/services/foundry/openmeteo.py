"""Open-Meteo live forecast and ensemble (CC BY 4.0, no key). PRD §8.4: forecast cache TTL 900 s.

Stored rows carry source, model, fetch time, source URL and licence. Past days returned by the forecast
API are model analyses, not observations, and are tagged as such.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import IST, now_utc, today_ist
from app.models.tables import WeatherForecast
from app.services.foundry.http import UpstreamError, get_json, ingest_run

LICENCE = "CC BY 4.0 (Open-Meteo.com)"
SOURCE = "open-meteo"
CACHE_TTL = timedelta(seconds=900)


@dataclass
class DayForecast:
    valid_date: date
    tmin_c: float | None
    tmax_c: float | None
    rain_mm: float | None
    precip_prob: float | None
    tmin_at: datetime | None = None        # hour of the minimum (IST)
    tmax_at: datetime | None = None
    tmin_spread_c: float | None = None     # ensemble standard deviation
    tmax_spread_c: float | None = None
    tmin_p10: float | None = None
    tmin_p90: float | None = None
    tmax_p10: float | None = None
    tmax_p90: float | None = None
    members: int = 0
    rain_p_heavy: float | None = None      # fraction of ensemble members with >= 64.5 mm (IMD "heavy")
    rain_members_max: float | None = None
    tmin_jma_c: float | None = None        # JMA GSM (models=jma_seamless): the forecast the frost model was trained on
    tmax_jma_c: float | None = None


@dataclass
class ForecastBundle:
    lat: float
    lon: float
    elevation_m: float | None
    fetched_at: datetime
    days: list[DayForecast]
    past_days: list[DayForecast] = field(default_factory=list)   # model analysis, not observation
    source_url: str = ""
    ensemble_model: str | None = None
    jma_model: str | None = None


def _quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        raise ValueError("empty")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fetch_forecast(lat: float, lon: float, days: int = 7, past_days: int = 7) -> ForecastBundle:
    s = get_settings()
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,precipitation_probability_max",
        "hourly": "temperature_2m",
        "timezone": "Asia/Kolkata", "forecast_days": days, "past_days": past_days,
    }
    data = get_json(s.open_meteo_forecast_url, params)
    fetched = now_utc()
    daily = data["daily"]
    hourly = data.get("hourly", {})
    by_day: dict[str, list[tuple[datetime, float]]] = {}
    for t, v in zip(hourly.get("time", []), hourly.get("temperature_2m", []), strict=False):
        if v is None:
            continue
        dt = datetime.fromisoformat(t).replace(tzinfo=IST)
        by_day.setdefault(t[:10], []).append((dt, v))
    out_future, out_past = [], []
    today = today_ist()
    for i, d in enumerate(daily["time"]):
        hrs = by_day.get(d, [])
        # The frost minimum of a date usually falls before sunrise; take the coldest hour 00:00 to 09:00.
        early = [h for h in hrs if h[0].hour <= 9] or hrs
        row = DayForecast(
            valid_date=date.fromisoformat(d),
            tmin_c=daily["temperature_2m_min"][i], tmax_c=daily["temperature_2m_max"][i],
            rain_mm=daily["precipitation_sum"][i], precip_prob=daily["precipitation_probability_max"][i],
            tmin_at=min(early, key=lambda h: h[1])[0] if early else None,
            tmax_at=max(hrs, key=lambda h: h[1])[0] if hrs else None,
        )
        (out_past if row.valid_date < today else out_future).append(row)
    bundle = ForecastBundle(lat=lat, lon=lon, elevation_m=data.get("elevation"), fetched_at=fetched,
                            days=out_future, past_days=out_past, source_url=s.open_meteo_forecast_url)
    try:
        _attach_ensemble(bundle, days)
    except UpstreamError:
        pass  # deterministic forecast still usable; the band is then absent, never invented
    try:
        _attach_jma(bundle, days)
    except UpstreamError:
        pass  # the frost model then receives best_match and says so in its evidence
    return bundle


def _attach_jma(bundle: ForecastBundle, days: int) -> None:
    """The frost/heat classifier was trained on archived JMA GSM forecasts; feeding it best_match lowers
    held-out skill (docs/model_cards/frost.md), so fetch JMA alongside the default forecast."""
    s = get_settings()
    model = "jma_seamless"
    data = get_json(s.open_meteo_forecast_url, {
        "latitude": round(bundle.lat, 4), "longitude": round(bundle.lon, 4),
        "daily": "temperature_2m_min,temperature_2m_max", "models": model,
        "timezone": "Asia/Kolkata", "forecast_days": days,
    })
    daily = data.get("daily", {})
    idx = {d: i for i, d in enumerate(daily.get("time", []))}
    for day in bundle.days:
        i = idx.get(day.valid_date.isoformat())
        if i is not None:
            day.tmin_jma_c = daily.get("temperature_2m_min", [None] * (i + 1))[i]
            day.tmax_jma_c = daily.get("temperature_2m_max", [None] * (i + 1))[i]
    if any(d.tmin_jma_c is not None for d in bundle.days):
        bundle.jma_model = model


def _attach_ensemble(bundle: ForecastBundle, days: int) -> None:
    s = get_settings()
    model = "ecmwf_ifs025"
    data = get_json(s.open_meteo_ensemble_url, {
        "latitude": round(bundle.lat, 4), "longitude": round(bundle.lon, 4),
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum", "models": model,
        "timezone": "Asia/Kolkata", "forecast_days": days,
    })
    daily = data.get("daily", {})
    idx = {d: i for i, d in enumerate(daily.get("time", []))}
    for day in bundle.days:
        i = idx.get(day.valid_date.isoformat())
        if i is None:
            continue
        for var, attr in (("temperature_2m_min", "tmin"), ("temperature_2m_max", "tmax")):
            vals = [daily[k][i] for k in daily if k.startswith(var + "_member") and daily[k][i] is not None]
            if var in daily and daily[var][i] is not None:
                vals.append(daily[var][i])  # control run
            if len(vals) >= 10:
                setattr(day, f"{attr}_spread_c", round(statistics.pstdev(vals), 2))
                setattr(day, f"{attr}_p10", round(_quantile(vals, 0.1), 2))
                setattr(day, f"{attr}_p90", round(_quantile(vals, 0.9), 2))
                day.members = len(vals)
        rain = [daily[k][i] for k in daily if k.startswith("precipitation_sum") and daily[k][i] is not None]
        if len(rain) >= 10:
            day.rain_p_heavy = round(sum(1 for r in rain if r >= 64.5) / len(rain), 3)
            day.rain_members_max = max(rain)
    bundle.ensemble_model = model


def store_forecast(db: Session, bundle: ForecastBundle, field_id: int | None) -> None:
    issued = bundle.fetched_at
    for day in bundle.days:
        lead = int((datetime.combine(day.valid_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=6) - issued)
                   .total_seconds() // 3600)
        db.add(WeatherForecast(
            field_id=field_id, lat=bundle.lat, lon=bundle.lon, issued_at=issued, valid_date=day.valid_date,
            lead_hours=max(lead, 0), tmin_c=day.tmin_c, tmax_c=day.tmax_c, rain_mm=day.rain_mm,
            precip_prob=day.precip_prob, source=SOURCE, model="best_match",
            tmin_spread_c=day.tmin_spread_c, tmax_spread_c=day.tmax_spread_c,
            source_url=bundle.source_url, licence=LICENCE, fetched_at=issued,
        ))
    db.flush()


_memory: dict[tuple[float, float], ForecastBundle] = {}


def get_forecast(db: Session, lat: float, lon: float, field_id: int | None = None, force: bool = False) -> ForecastBundle:
    """Forecast for a point, re-fetched at most every 900 s (PRD §8.4). Raises UpstreamError if
    Open-Meteo is down and nothing fresh is cached."""
    key = (round(lat, 3), round(lon, 3))
    cached = _memory.get(key)
    if cached and not force and now_utc() - cached.fetched_at < CACHE_TTL:
        return cached
    with ingest_run(db, "open-meteo-forecast", lat=key[0], lon=key[1], field_id=field_id) as run:
        bundle = fetch_forecast(lat, lon)
        if field_id is not None:
            # keep only the latest issue per field to bound table growth; history lives in decisions.inputs
            db.execute(delete(WeatherForecast).where(WeatherForecast.field_id == field_id,
                                                     WeatherForecast.issued_at < now_utc() - timedelta(days=3)))
        store_forecast(db, bundle, field_id)
        run.records = len(bundle.days)
    _memory[key] = bundle
    return bundle


def latest_stored(db: Session, field_id: int) -> list[WeatherForecast]:
    issued = db.execute(select(WeatherForecast.issued_at).where(WeatherForecast.field_id == field_id)
                        .order_by(WeatherForecast.issued_at.desc()).limit(1)).scalar_one_or_none()
    if issued is None:
        return []
    return list(db.execute(select(WeatherForecast).where(WeatherForecast.field_id == field_id,
                                                         WeatherForecast.issued_at == issued)
                           .order_by(WeatherForecast.valid_date)).scalars())


def bundle_to_json(b: ForecastBundle) -> dict[str, Any]:
    def d(x: DayForecast) -> dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, date | datetime) else v) for k, v in x.__dict__.items()}
    return {"lat": b.lat, "lon": b.lon, "elevation_m": b.elevation_m, "fetched_at": b.fetched_at.isoformat(),
            "source_url": b.source_url, "ensemble_model": b.ensemble_model, "jma_model": b.jma_model,
            "days": [d(x) for x in b.days], "past_days": [d(x) for x in b.past_days]}
