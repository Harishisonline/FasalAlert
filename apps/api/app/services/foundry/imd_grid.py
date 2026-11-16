"""IMD Pune gridded daily data: download, parse and tidy, with provenance.

Sources (Climate Research and Services, IMD Pune, government open data):
  * Minimum temperature, 1.0 x 1.0 degree, 1951 onward:
      https://www.imdpune.gov.in/cmpg/Griddata/Min_1_Bin.html  (form POST to mintemp.php, field "mintemp")
  * Maximum temperature, 1.0 x 1.0 degree, 1951 onward:
      https://www.imdpune.gov.in/cmpg/Griddata/Max_1_Bin.html  (form POST to maxtemp.php, field "maxtemp")
  * Rainfall, 0.25 x 0.25 degree, 1901 onward:
      https://www.imdpune.gov.in/cmpg/Griddata/Rainfall_25_Bin.html  (form POST to rainfall.php, field "rain")

File formats, as documented on those pages:
  * Temperature: little-endian float32, one 31 x 31 record per day (365 or 366 records). Latitude
    7.5N..37.5N, longitude 67.5E..97.5E, both at 1 degree, longitude varies fastest. Missing = 99.9.
  * Rainfall: little-endian float32, one 129 (lat) x 135 (lon) record per day. Latitude 6.5N..38.5N,
    longitude 66.5E..100.0E at 0.25 degree, longitude varies fastest. Missing = -999.0. Unit mm.

IMD notes that grids from 2008 onward are built from fewer stations (about 180, real time). That is a
known inhomogeneity of the record and is reported in the model card, not corrected here.

Everything downloaded is cached under data/raw_external/imd/ (gitignored) with a JSON sidecar holding
the URL, form field, HTTP status, served filename, byte count, SHA-256 and download time.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
import pandas as pd
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import DATA_DIR

log = logging.getLogger("fasalalert.foundry.imd_grid")

Var = Literal["tmin", "tmax", "rain"]

BASE = "https://www.imdpune.gov.in/cmpg/Griddata"
LICENCE = "Government of India open data (IMD Pune, Climate Research and Services)"


@dataclass(frozen=True)
class GridSpec:
    var: Var
    page: str
    endpoint: str
    form_field: str
    lat0: float
    lon0: float
    nlat: int
    nlon: int
    step: float
    undef: float
    first_year: int


SPECS: dict[str, GridSpec] = {
    "tmin": GridSpec("tmin", f"{BASE}/Min_1_Bin.html", f"{BASE}/mintemp.php", "mintemp",
                     7.5, 67.5, 31, 31, 1.0, 99.9, 1951),
    "tmax": GridSpec("tmax", f"{BASE}/Max_1_Bin.html", f"{BASE}/maxtemp.php", "maxtemp",
                     7.5, 67.5, 31, 31, 1.0, 99.9, 1951),
    "rain": GridSpec("rain", f"{BASE}/Rainfall_25_Bin.html", f"{BASE}/rainfall.php", "rain",
                     6.5, 66.5, 129, 135, 0.25, -999.0, 1901),
}

DEFAULT_CACHE = DATA_DIR / "raw_external" / "imd"

# Approximate Maharashtra outline (lon, lat), hand-digitised at roughly 0.1 to 0.3 degree accuracy.
# It is only used to choose which 1 degree IMD cells count as "Maharashtra"; a cell is kept when at
# least 30% of its 1 x 1 degree box falls inside this outline.
MAHARASHTRA_OUTLINE: list[tuple[float, float]] = [
    (72.70, 20.20), (72.90, 20.60), (73.40, 20.70), (73.60, 21.10), (73.80, 21.60), (74.10, 22.00),
    (74.60, 21.90), (75.20, 21.50), (75.80, 21.40), (76.20, 21.60), (76.60, 21.30), (77.00, 21.70),
    (77.50, 21.50), (78.10, 21.70), (78.60, 21.60), (79.10, 21.60), (79.60, 21.70), (80.10, 21.70),
    (80.60, 21.50), (80.90, 21.20), (80.60, 20.70), (80.50, 20.00), (80.40, 19.50), (80.20, 19.00),
    (80.00, 18.60), (79.70, 18.70), (79.40, 19.20), (79.10, 19.50), (78.70, 19.80), (78.30, 19.80),
    (78.00, 19.50), (77.60, 19.20), (77.50, 18.60), (77.40, 18.20), (77.10, 17.80), (76.70, 17.60),
    (76.30, 17.30), (75.90, 17.20), (75.70, 17.00), (75.40, 16.70), (75.00, 16.50), (74.60, 16.20),
    (74.30, 15.90), (74.10, 15.70), (73.70, 15.70), (73.40, 16.10), (73.30, 16.70), (73.10, 17.50),
    (72.95, 18.30), (72.85, 18.90), (72.80, 19.50), (72.70, 20.20),
]


def grid_axes(spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    lats = spec.lat0 + spec.step * np.arange(spec.nlat)
    lons = spec.lon0 + spec.step * np.arange(spec.nlon)
    return lats, lons


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


def _user_agent() -> str:
    try:
        from app.core.config import get_settings

        return get_settings().http_user_agent
    except (ImportError, ValueError):  # settings are optional for offline training
        return "FasalAlert/0.1 (research)"


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(4),
       wait=wait_exponential(multiplier=2, max=60), reraise=True)
def _post(url: str, data: dict[str, str], timeout: float) -> httpx.Response:
    with httpx.Client(timeout=timeout, headers={"User-Agent": _user_agent()}, follow_redirects=True) as c:
        r = c.post(url, data=data)
        r.raise_for_status()
        return r


def cache_path(var: Var, year: int, cache_dir: Path = DEFAULT_CACHE) -> Path:
    return cache_dir / var / f"{var}_{year}.grd"


def download_year(var: Var, year: int, cache_dir: Path = DEFAULT_CACHE, force: bool = False,
                  timeout: float = 300.0) -> Path:
    """Download one year of one IMD grid (cached). Returns the path of the binary file."""
    spec = SPECS[var]
    path = cache_path(var, year, cache_dir)
    meta = path.with_suffix(".json")
    if path.exists() and meta.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    r = _post(spec.endpoint, {spec.form_field: str(year)}, timeout)
    body = r.content
    rec = spec.nlat * spec.nlon * 4
    if len(body) == 0 or len(body) % rec != 0:
        raise ValueError(f"IMD {var} {year}: {len(body)} bytes is not a whole number of {rec}-byte daily records "
                         f"(content-type {r.headers.get('content-type')})")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(path)
    meta.write_text(json.dumps({
        "source": "IMD Pune gridded daily data",
        "variable": var,
        "year": year,
        "page": spec.page,
        "url": spec.endpoint,
        "method": "POST",
        "form": {spec.form_field: str(year)},
        "http_status": r.status_code,
        "served_filename": r.headers.get("content-disposition"),
        "bytes": len(body),
        "n_days": len(body) // rec,
        "sha256": hashlib.sha256(body).hexdigest(),
        "downloaded_at": datetime.now(UTC).isoformat(),
        "licence": LICENCE,
    }, indent=2))
    log.info("IMD %s %s downloaded, %d bytes", var, year, len(body))
    return path


def download_years(var: Var, years: list[int] | range, cache_dir: Path = DEFAULT_CACHE,
                   pause_s: float = 1.0) -> list[Path]:
    out = []
    for y in years:
        cached = cache_path(var, y, cache_dir)
        fresh = not (cached.exists() and cached.with_suffix(".json").exists())
        out.append(download_year(var, y, cache_dir))
        if fresh:
            time.sleep(pause_s)  # be polite to imdpune.gov.in
    return out


def read_grid(var: Var, path: Path) -> np.ndarray:
    """Read a binary grid file into an array (n_days, nlat, nlon) with NaN for missing."""
    spec = SPECS[var]
    raw = np.fromfile(path, dtype="<f4")
    rec = spec.nlat * spec.nlon
    if raw.size % rec:
        raise ValueError(f"{path}: size {raw.size} is not a multiple of {rec}")
    arr = raw.reshape(-1, spec.nlat, spec.nlon).astype(np.float64)
    if var == "rain":
        arr[arr <= -998.0] = np.nan
    else:
        arr[arr >= 99.0] = np.nan
    return arr


def provenance(var: Var, years: list[int] | range, cache_dir: Path = DEFAULT_CACHE) -> list[dict]:
    rows = []
    for y in years:
        meta = cache_path(var, y, cache_dir).with_suffix(".json")
        if meta.exists():
            m = json.loads(meta.read_text())
            rows.append({k: m.get(k) for k in ("variable", "year", "url", "form", "bytes", "n_days", "sha256",
                                               "downloaded_at")})
    return rows


def maharashtra_cells(min_fraction: float = 0.3) -> list[tuple[float, float]]:
    """1 degree IMD temperature cells (centre lat, lon) whose box is at least `min_fraction` inside the
    approximate Maharashtra outline."""
    from shapely.geometry import Polygon, box

    poly = Polygon(MAHARASHTRA_OUTLINE)
    lats, lons = grid_axes(SPECS["tmin"])
    cells = []
    for la in lats:
        for lo in lons:
            cell = box(lo - 0.5, la - 0.5, lo + 0.5, la + 0.5)
            if cell.intersection(poly).area / cell.area >= min_fraction:
                cells.append((float(la), float(lo)))
    return cells


def tidy_temperature(var: Literal["tmin", "tmax"], years: list[int] | range,
                     cells: list[tuple[float, float]], cache_dir: Path = DEFAULT_CACHE,
                     download: bool = True) -> pd.DataFrame:
    """Long table: date, lat, lon, <var> (deg C). Rows with missing values are dropped."""
    spec = SPECS[var]
    lats, lons = grid_axes(spec)
    li = [int(round((la - spec.lat0) / spec.step)) for la, _ in cells]
    lj = [int(round((lo - spec.lon0) / spec.step)) for _, lo in cells]
    frames = []
    for y in years:
        path = download_year(var, y, cache_dir) if download else cache_path(var, y, cache_dir)
        arr = read_grid(var, path)
        nd = arr.shape[0]
        if nd != days_in_year(y):
            log.warning("IMD %s %s has %d days (expected %d)", var, y, nd, days_in_year(y))
        dates = pd.date_range(date(y, 1, 1), periods=nd, freq="D")
        vals = arr[:, li, lj]  # (nd, ncells)
        df = pd.DataFrame({
            "date": np.repeat(dates.values, len(cells)),
            "lat": np.tile([c[0] for c in cells], nd),
            "lon": np.tile([c[1] for c in cells], nd),
            var: vals.reshape(-1),
        })
        frames.append(df.dropna(subset=[var]))
    out = pd.concat(frames, ignore_index=True)
    out.attrs["source"] = f"IMD Pune 1.0 degree gridded daily {var} ({spec.page})"
    return out


def tidy_rain_on_1deg(years: list[int] | range, cells: list[tuple[float, float]],
                      cache_dir: Path = DEFAULT_CACHE, download: bool = True) -> pd.DataFrame:
    """IMD 0.25 degree rainfall averaged onto the 1 degree temperature cells (mean of the 0.25 degree
    points whose centres fall inside each 1 x 1 degree box). Long table: date, lat, lon, rain (mm)."""
    spec = SPECS["rain"]
    rlats, rlons = grid_axes(spec)
    frames = []
    for y in years:
        path = download_year("rain", y, cache_dir) if download else cache_path("rain", y, cache_dir)
        arr = read_grid("rain", path)
        nd = arr.shape[0]
        dates = pd.date_range(date(y, 1, 1), periods=nd, freq="D")
        cols = {}
        for la, lo in cells:
            mi = (rlats >= la - 0.5) & (rlats < la + 0.5)
            mj = (rlons >= lo - 0.5) & (rlons < lo + 0.5)
            sub = arr[:, mi][:, :, mj].reshape(nd, -1)
            with np.errstate(all="ignore"):
                cols[(la, lo)] = np.where(np.isfinite(sub).any(1), np.nanmean(sub, axis=1), np.nan)
        df = pd.DataFrame({
            "date": np.repeat(dates.values, len(cells)),
            "lat": np.tile([c[0] for c in cells], nd),
            "lon": np.tile([c[1] for c in cells], nd),
            "rain": np.stack([cols[c] for c in cells], axis=1).reshape(-1),
        })
        frames.append(df.dropna(subset=["rain"]))
    out = pd.concat(frames, ignore_index=True)
    out.attrs["source"] = f"IMD Pune 0.25 degree gridded daily rainfall, averaged to 1 degree ({spec.page})"
    return out


if __name__ == "__main__":  # manual: uv run python -m app.services.foundry.imd_grid tmin 1951 2025
    import sys

    logging.basicConfig(level=logging.INFO)
    v, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    download_years(v, range(a, b + 1))  # type: ignore[arg-type]
