"""Archived Open-Meteo forecasts for training the frost and heat classifier (PRD §9.1).

Live serving uses app/services/foundry/openmeteo.py. This module only fetches history:

  * Previous Runs API (https://previous-runs-api.open-meteo.com/v1/forecast, CC BY 4.0, no key).
    For every hourly time t, `<var>_previous_dayN` is the value at t from the model run issued about N
    days before the run that produced the day-0 value. With 6-hourly JMA runs the lead of a
    previous_dayN value is about N*24 to N*24+6 hours. Daily Tmin, Tmax and rain are aggregated from the
    24 hourly values of each local (Asia/Kolkata) calendar day, which is how the live daily
    temperature_2m_min / _max of the forecast API are defined.
  * Elevation API (https://api.open-meteo.com/v1/elevation): 90 m DEM height of each requested point.

Coverage probed on 2026-11-02 at 19.5N 74.5E (the archive keeps no record of this, so it is restated in
the model card): jma_seamless has previous_day1 and previous_day2 from 2016-01-01 and previous_day3 from
2019; the other global models (GFS, ECMWF IFS, ICON, best_match) start later or have gaps. JMA GSM is
therefore the only model that gives 10 winters at a 48 h lead.

Responses are cached gzip-compressed under data/raw_external/openmeteo/ (gitignored) with a JSON sidecar
(URL, parameters, HTTP status, bytes, SHA-256, time). Requests are paced under Open-Meteo's free-tier
limits, counting the fractional call weight (locations x days/14 x variables/10).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import DATA_DIR

log = logging.getLogger("fasalalert.foundry.openmeteo_history")

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
LICENCE = "CC BY 4.0 (Open-Meteo.com; JMA GSM by the Japan Meteorological Agency)"
DEFAULT_CACHE = DATA_DIR / "raw_external" / "openmeteo"
TIMEZONE = "Asia/Kolkata"
LEADS = (1, 2, 3)
PR_VARS = tuple(f"{v}_previous_day{n}" for v in ("temperature_2m", "precipitation") for n in LEADS)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TransportError, json.JSONDecodeError)):
        return True  # includes the occasional empty 200 body
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


def _user_agent() -> str:
    try:
        from app.core.config import get_settings

        return get_settings().http_user_agent
    except (ImportError, ValueError):  # settings are optional for offline training
        return "FasalAlert/0.1 (research)"


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(6),
       wait=wait_exponential(multiplier=5, min=5, max=300), reraise=True)
def _get(url: str, params: dict[str, Any], timeout: float = 120.0) -> httpx.Response:
    with httpx.Client(timeout=timeout, headers={"User-Agent": _user_agent()}) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        json.loads(r.content)  # raise (and retry) on a truncated or empty body
        return r


class _Pacer:
    """Keeps the request weight under `per_minute` fractional calls per rolling minute."""

    def __init__(self, per_minute: float = 60.0) -> None:
        self.per_minute = per_minute
        self.log: list[tuple[float, float]] = []

    def wait(self, weight: float) -> None:
        while True:
            now = time.monotonic()
            self.log = [(t, w) for t, w in self.log if now - t < 60.0]
            if sum(w for _, w in self.log) + weight <= self.per_minute or not self.log:
                self.log.append((now, weight))
                return
            time.sleep(max(0.5, 60.0 - (now - self.log[0][0])))


_PACER = _Pacer()


def call_weight(n_locations: int, n_days: int, n_vars: int) -> float:
    return n_locations * max(1.0, n_days / 14.0) * max(1.0, n_vars / 10.0)


def _key(lat: float, lon: float) -> str:
    return f"{lat:.2f}_{lon:.2f}"


def previous_runs_path(model: str, lat: float, lon: float, start: date, end: date,
                       cache_dir: Path = DEFAULT_CACHE) -> Path:
    return cache_dir / "previous_runs" / model / f"{_key(lat, lon)}_{start}_{end}.json.gz"


def fetch_previous_runs(lat: float, lon: float, start: date, end: date, model: str = "jma_seamless",
                        variables: tuple[str, ...] = PR_VARS, cache_dir: Path = DEFAULT_CACHE,
                        offline: bool = False) -> dict[str, Any]:
    """Hourly previous-runs values for one point and date range (cached)."""
    path = previous_runs_path(model, lat, lon, start, end, cache_dir)
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    if offline:
        raise FileNotFoundError(path)
    params = {
        "latitude": lat, "longitude": lon, "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": ",".join(variables), "models": model, "timezone": TIMEZONE,
    }
    _PACER.wait(call_weight(1, (end - start).days + 1, len(variables)))
    r = _get(PREVIOUS_RUNS_URL, params)
    body = r.content
    data = json.loads(body)
    if data.get("error"):
        raise RuntimeError(f"Open-Meteo error for {params}: {data.get('reason')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(gzip.compress(body))
    tmp.replace(path)
    path.with_suffix("").with_suffix(".meta.json").write_text(json.dumps({
        "url": PREVIOUS_RUNS_URL, "params": params, "http_status": r.status_code, "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "downloaded_at": datetime.now(UTC).isoformat(),
        "licence": LICENCE,
    }, indent=2))
    return data


def previous_runs_daily(data: dict[str, Any], lat: float, lon: float, min_hours: int = 20) -> pd.DataFrame:
    """Aggregate hourly previous-runs JSON to one row per local day:
    date, lat, lon, f_tmin_d{N}, f_tmax_d{N}, f_rain_d{N} for N in 1..3 (NaN if fewer than `min_hours`)."""
    h = data.get("hourly", {})
    times = pd.to_datetime(h.get("time", []))
    if len(times) == 0:
        return pd.DataFrame()
    df = pd.DataFrame({"time": times})
    for n in LEADS:
        df[f"t{n}"] = pd.to_numeric(pd.Series(h.get(f"temperature_2m_previous_day{n}", [None] * len(times))),
                                    errors="coerce").to_numpy(dtype=float)
        df[f"p{n}"] = pd.to_numeric(pd.Series(h.get(f"precipitation_previous_day{n}", [None] * len(times))),
                                    errors="coerce").to_numpy(dtype=float)
    df["date"] = df["time"].dt.normalize()
    g = df.groupby("date")
    out = pd.DataFrame(index=g.size().index)
    for n in LEADS:
        cnt = g[f"t{n}"].count()
        ok = cnt >= min_hours
        out[f"f_tmin_d{n}"] = g[f"t{n}"].min().where(ok)
        out[f"f_tmax_d{n}"] = g[f"t{n}"].max().where(ok)
        pc = g[f"p{n}"].count()
        out[f"f_rain_d{n}"] = g[f"p{n}"].sum(min_count=1).where(pc >= min_hours)
    out = out.reset_index()
    out.insert(1, "lat", lat)
    out.insert(2, "lon", lon)
    out.attrs["om_elevation_m"] = data.get("elevation")
    out.attrs["om_lat"] = data.get("latitude")
    out.attrs["om_lon"] = data.get("longitude")
    return out


def season_windows(year: int, first: date = date(2016, 1, 1), last: date = date(2025, 12, 31)) -> list[tuple[date, date]]:
    """The two windows per calendar year used for training: Jan 1 to Jun 15 (late frost season and the
    heat season) and Nov 15 to Dec 31 (early frost season)."""
    wins = [(date(year, 1, 1), date(year, 6, 15)), (date(year, 11, 15), date(year, 12, 31))]
    return [(max(a, first), min(b, last)) for a, b in wins if min(b, last) >= max(a, first)]


def scoring_windows(year: int, first: date = date(2021, 12, 1), last: date = date(2025, 12, 31)) -> list[tuple[date, date]]:
    """Scoring months only (Dec to Feb frost, Mar to May heat): Jan 1 to May 31 and Dec 1 to Dec 31.
    Used for the evaluation-only download of the model that live serving uses (best_match)."""
    wins = [(date(year, 1, 1), date(year, 5, 31)), (date(year, 12, 1), date(year, 12, 31))]
    return [(max(a, first), min(b, last)) for a, b in wins if min(b, last) >= max(a, first)]


def download_cells(cells: list[tuple[float, float]], years: list[int] | range, model: str = "jma_seamless",
                   cache_dir: Path = DEFAULT_CACHE, offline: bool = False,
                   windows: Callable[[int], list[tuple[date, date]]] = season_windows) -> pd.DataFrame:
    """Daily forecast table for all cells and windows (downloads what is not cached)."""
    frames = []
    meta = {}
    total = len(cells) * sum(len(windows(y)) for y in years)
    k = 0
    for la, lo in cells:
        for y in years:
            for a, b in windows(y):
                k += 1
                cached = previous_runs_path(model, la, lo, a, b, cache_dir).exists()
                data = fetch_previous_runs(la, lo, a, b, model=model, cache_dir=cache_dir, offline=offline)
                d = previous_runs_daily(data, la, lo)
                meta[(la, lo)] = (data.get("elevation"), data.get("latitude"), data.get("longitude"))
                frames.append(d)
                if not cached:
                    log.info("previous runs %s %s %s..%s (%d/%d)", model, (la, lo), a, b, k, total)
    out = pd.concat([f for f in frames if len(f)], ignore_index=True)
    el = pd.DataFrame([(la, lo, *v) for (la, lo), v in meta.items()],
                      columns=["lat", "lon", "om_elevation_m", "om_grid_lat", "om_grid_lon"])
    return out.merge(el, on=["lat", "lon"], how="left")


def fetch_elevation(points: list[tuple[float, float]], cache_dir: Path = DEFAULT_CACHE,
                    offline: bool = False) -> dict[tuple[float, float], float]:
    """90 m DEM elevation (m) for points, cached as one JSON file."""
    path = cache_dir / "elevation.json"
    cache: dict[str, float] = json.loads(path.read_text()) if path.exists() else {}
    missing = [p for p in points if _key(*p) not in cache]
    if missing and not offline:
        for i in range(0, len(missing), 100):
            chunk = missing[i:i + 100]
            _PACER.wait(1.0)
            r = _get(ELEVATION_URL, {"latitude": ",".join(f"{p[0]}" for p in chunk),
                                     "longitude": ",".join(f"{p[1]}" for p in chunk)})
            for p, e in zip(chunk, r.json()["elevation"], strict=True):
                cache[_key(*p)] = float(e)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return {p: cache[_key(*p)] for p in points if _key(*p) in cache}


def cache_inventory(model: str = "jma_seamless", cache_dir: Path = DEFAULT_CACHE) -> dict[str, Any]:
    files = sorted((cache_dir / "previous_runs" / model).glob("*.json.gz"))
    return {"model": model, "n_files": len(files), "bytes_gz": int(sum(f.stat().st_size for f in files)),
            "bytes_raw": int(sum(json.loads(f.with_suffix("").with_suffix(".meta.json").read_text())["bytes"]
                                 for f in files if f.with_suffix("").with_suffix(".meta.json").exists()))}


if __name__ == "__main__":  # manual: uv run python -m app.services.foundry.openmeteo_history
    import sys

    from app.services.foundry.imd_grid import maharashtra_cells

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    model = sys.argv[1] if len(sys.argv) > 1 else "jma_seamless"
    cells = maharashtra_cells()
    fetch_elevation(cells)
    if model == "jma_seamless":
        df = download_cells(cells, range(2016, 2026), model=model)
    else:  # evaluation-only archive of another model, scoring months 2021-12 to 2025-12
        df = download_cells(cells, range(2021, 2026), model=model, windows=scoring_windows)
    print(df.shape, np.isfinite(df.filter(like="f_tmin")).mean().round(3).to_dict())
