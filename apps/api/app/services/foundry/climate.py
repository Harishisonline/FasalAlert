"""Daily temperature history for a point: ERA5 reanalysis from the Open-Meteo archive (about 5 days lag)
joined to the forecast API's recent past days. Used for GDD accumulation (phenology).

These values are labelled "reanalysis", never "observed": IMD station or gridded observations live
under their own source names and are not silently replaced (data foundry rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import today_ist
from app.models.tables import WeatherObservation
from app.services.foundry.http import UpstreamError, get_json, ingest_run

ERA5_SOURCE = "open-meteo-archive-era5"
LICENCE = "CC BY 4.0 (Open-Meteo.com; ERA5 by ECMWF / Copernicus)"


@dataclass(frozen=True)
class DailyTemp:
    day: date
    tmin_c: float | None
    tmax_c: float | None
    rain_mm: float | None
    source: str


def _grid_key(lat: float, lon: float) -> str:
    # ERA5 is about 0.25 degrees; snap to 0.1 so nearby fields share cached rows.
    return f"g{round(lat, 1):.1f}_{round(lon, 1):.1f}"


def fetch_archive(lat: float, lon: float, start: date, end: date) -> list[DailyTemp]:
    s = get_settings()
    data = get_json(s.open_meteo_archive_url, {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum", "timezone": "Asia/Kolkata",
    }, timeout=60)
    d = data.get("daily", {})
    return [DailyTemp(date.fromisoformat(t), d["temperature_2m_min"][i], d["temperature_2m_max"][i],
                      d["precipitation_sum"][i], ERA5_SOURCE) for i, t in enumerate(d.get("time", []))]


def daily_history(db: Session, lat: float, lon: float, start: date, end: date | None = None) -> list[DailyTemp]:
    """Daily Tmin/Tmax/rain from start to end (inclusive), cached in weather_observations."""
    end = end or today_ist() - timedelta(days=1)
    key = _grid_key(lat, lon)
    rows = db.execute(select(WeatherObservation).where(
        WeatherObservation.station_id == key, WeatherObservation.source == ERA5_SOURCE,
        WeatherObservation.obs_date >= start, WeatherObservation.obs_date <= end,
    )).scalars().all()
    have = {r.obs_date: r for r in rows if r.tmin_c is not None}
    archive_end = min(end, today_ist() - timedelta(days=6))
    missing = [start + timedelta(days=i) for i in range((archive_end - start).days + 1)
               if start + timedelta(days=i) not in have]
    if missing:
        with ingest_run(db, "open-meteo-archive", key=key, start=str(missing[0]), end=str(missing[-1])) as run:
            fetched = fetch_archive(lat, lon, missing[0], missing[-1])
            vals = [{"station_id": key, "station_name": "ERA5 grid (Open-Meteo archive)", "lat": round(lat, 1),
                     "lon": round(lon, 1), "obs_date": r.day, "tmin_c": r.tmin_c, "tmax_c": r.tmax_c,
                     "rain_mm": r.rain_mm, "source": ERA5_SOURCE, "source_url": get_settings().open_meteo_archive_url,
                     "licence": LICENCE, "quality": "ok" if r.tmin_c is not None else "missing"} for r in fetched]
            if vals:
                stmt = insert(WeatherObservation).values(vals)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["station_id", "obs_date", "source"],
                    set_={"tmin_c": stmt.excluded.tmin_c, "tmax_c": stmt.excluded.tmax_c,
                          "rain_mm": stmt.excluded.rain_mm, "quality": stmt.excluded.quality},
                )
                db.execute(stmt)
            run.records = len(vals)
            for r in fetched:
                if r.tmin_c is not None:
                    have[r.day] = r  # type: ignore[assignment]
    out = [DailyTemp(d, v.tmin_c, v.tmax_c, v.rain_mm, ERA5_SOURCE) for d, v in sorted(have.items())]
    return out


def recent_with_forecast_past(db: Session, lat: float, lon: float, start: date) -> list[DailyTemp]:
    """History from `start` to yesterday: ERA5 archive up to 6 days ago, then the forecast model's own
    analysis for the last days (tagged 'open-meteo-forecast-past')."""
    from app.services.foundry.openmeteo import get_forecast

    hist = daily_history(db, lat, lon, start)
    last = hist[-1].day if hist else start - timedelta(days=1)
    try:
        bundle = get_forecast(db, lat, lon)
        for d in bundle.past_days:
            if d.valid_date > last:
                hist.append(DailyTemp(d.valid_date, d.tmin_c, d.tmax_c, d.rain_mm, "open-meteo-forecast-past"))
    except UpstreamError:
        pass
    return hist
