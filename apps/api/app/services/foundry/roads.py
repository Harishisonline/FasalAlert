"""Route from field to mandi (OSRM over OpenStreetMap, ODbL) and SRTM elevation (OpenTopoData).

OSRM returns route geometry and road names/refs per step but not OSM way ids. Segments built from
OSRM geometry are stored with source='osrm-geometry' and a negative synthetic osm_id, so they are never
confused with real OSM way ids. Road class is inferred from the official route reference (NH, SH, MDR).
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services.foundry.http import get_json

OSM_ATTRIBUTION = "Routes © OpenStreetMap contributors (ODbL), routed with OSRM; elevation SRTM 30 m via OpenTopoData"


@dataclass
class Segment:
    coords: list[tuple[float, float]]           # (lon, lat)
    name: str | None
    ref: str | None
    road_class: str
    length_km: float
    min_elev_m: float | None = None
    max_elev_m: float | None = None
    slope_pct: float | None = None
    low_lying: bool | None = None
    elevations: list[float] = field(default_factory=list)

    @property
    def midpoint(self) -> tuple[float, float]:
        lon, lat = self.coords[len(self.coords) // 2]
        return lat, lon

    def synthetic_id(self) -> int:
        h = hashlib.sha1(f"{self.coords[0]}{self.coords[-1]}{len(self.coords)}".encode()).hexdigest()
        return -int(h[:15], 16)


@dataclass
class Route:
    distance_km: float
    duration_min: float
    name: str
    segments: list[Segment]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    p = math.pi / 180
    h = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def road_class_from_ref(ref: str | None, name: str | None) -> str:
    r = (ref or "").upper().replace(" ", "")
    if r.startswith("NH") or r.startswith("AH"):
        return "national"
    if r.startswith("SH") or r.startswith("MSH"):
        return "state"
    if r.startswith("MDR") or r.startswith("ODR"):
        return "district"
    if name:
        return "other"
    return "village"


def fetch_route(field_ll: tuple[float, float], mandi_ll: tuple[float, float]) -> Route:
    """field_ll, mandi_ll are (lat, lon)."""
    s = get_settings()
    a, b = field_ll, mandi_ll
    url = f"{s.osrm_url}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}"
    data = get_json(url, {"overview": "full", "geometries": "geojson", "steps": "true"}, timeout=40)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"no route ({data.get('code')})")
    r = data["routes"][0]
    steps = [st for leg in r["legs"] for st in leg["steps"]]
    segments = _segments_from_steps(steps)
    refs = [s_.ref for s_ in segments if s_.ref]
    main = max(set(refs), key=lambda x: sum(s_.length_km for s_ in segments if s_.ref == x)) if refs else None
    name = f"{main} route" if main else "Local roads"
    return Route(distance_km=r["distance"] / 1000, duration_min=r["duration"] / 60, name=name, segments=segments)


def _segments_from_steps(steps: list[dict], target_km: float = 5.0) -> list[Segment]:
    """Merge consecutive steps of the same road into pieces of about target_km."""
    out: list[Segment] = []
    cur: Segment | None = None
    for st in steps:
        coords = [tuple(c) for c in st["geometry"]["coordinates"]]
        if len(coords) < 2:
            continue
        ref = (st.get("ref") or "").split(";")[0].strip() or None
        name = st.get("name") or None
        cls = road_class_from_ref(ref, name)
        km = st["distance"] / 1000
        if cur is not None and cur.ref == ref and cur.road_class == cls and cur.length_km + km <= target_km * 1.5:
            cur.coords.extend(coords[1:])
            cur.length_km += km
        else:
            cur = Segment(coords=list(coords), name=name, ref=ref, road_class=cls, length_km=km)
            out.append(cur)
    # split long pieces so elevation and rain are sampled along long highways
    split: list[Segment] = []
    for seg in out:
        if seg.length_km <= target_km * 1.5:
            split.append(seg)
            continue
        acc, piece = 0.0, [seg.coords[0]]
        for p, q in zip(seg.coords, seg.coords[1:], strict=False):
            acc += haversine_km(p, q)
            piece.append(q)
            if acc >= target_km:
                split.append(Segment(piece, seg.name, seg.ref, seg.road_class, acc))
                acc, piece = 0.0, [q]
        if len(piece) > 1:
            split.append(Segment(piece, seg.name, seg.ref, seg.road_class, acc))
    return [s_ for s_ in split if s_.length_km > 0.05]


def _sample(coords: list[tuple[float, float]], every_km: float) -> list[tuple[float, float]]:
    pts, acc = [coords[0]], 0.0
    for p, q in zip(coords, coords[1:], strict=False):
        acc += haversine_km(p, q)
        if acc >= every_km:
            pts.append(q)
            acc = 0.0
    if pts[-1] != coords[-1]:
        pts.append(coords[-1])
    return pts


def attach_elevation(route: Route, every_km: float = 1.0) -> None:
    """OpenTopoData public API: at most 100 locations per request and 1 request per second."""
    s = get_settings()
    samples: list[tuple[int, tuple[float, float]]] = []
    for i, seg in enumerate(route.segments):
        samples += [(i, p) for p in _sample(seg.coords, every_km)]
    for start in range(0, len(samples), 100):
        chunk = samples[start:start + 100]
        locs = "|".join(f"{lat:.5f},{lon:.5f}" for _, (lon, lat) in chunk)
        data = get_json(s.opentopodata_url, {"locations": locs}, timeout=40)
        for (i, _), res in zip(chunk, data.get("results", []), strict=False):
            if res.get("elevation") is not None:
                route.segments[i].elevations.append(float(res["elevation"]))
        time.sleep(1.1)
    all_e = [e for seg in route.segments for e in seg.elevations]
    for idx, seg in enumerate(route.segments):
        if not seg.elevations:
            continue
        seg.min_elev_m, seg.max_elev_m = min(seg.elevations), max(seg.elevations)
        seg.slope_pct = round(100 * (seg.max_elev_m - seg.min_elev_m) / max(seg.length_km * 1000, 1), 2)
        seg.low_lying = _is_dip(route.segments, idx, all_e)


def _is_dip(segs: list[Segment], idx: int, all_e: list[float], rise_m: float = 10.0) -> bool:
    """Drainage proxy: the segment holds a local elevation minimum with at least rise_m of ground rising
    on both sides along the route (a valley floor or stream crossing)."""
    seg = segs[idx]
    if seg.min_elev_m is None:
        return False
    before = [e for s_ in segs[max(0, idx - 2):idx] for e in s_.elevations] + seg.elevations[: max(1, len(seg.elevations) // 2)]
    after = seg.elevations[len(seg.elevations) // 2:] + [e for s_ in segs[idx + 1: idx + 3] for e in s_.elevations]
    if not before or not after:
        return False
    return max(before) - seg.min_elev_m >= rise_m and max(after) - seg.min_elev_m >= rise_m
