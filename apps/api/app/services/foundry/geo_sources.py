"""Maharashtra geographic reference data: download, cache and normalise every licensed source.

Sources (each record keeps its provenance; see apps/api/data/geo/SOURCE.md):

* Wikidata (CC0): districts and talukas, English/Marathi/Hindi labels, LGD codes, coordinates.
* geoBoundaries gbOpen India ADM1/ADM2/ADM3 (ADM2/ADM3 ODbL 1.0, ADM1 CC BY 2.5 IN): district and
  sub-district polygons. ADM1 is used only as a spatial filter for Maharashtra.
* OpenStreetMap via Overpass (ODbL 1.0): village, hamlet and town nodes; settlement nodes for geocoding.
* AGMARKNET 2.0 public API (Government of India open data): APMC market names and the commodities
  each market reports. Only endpoints that need no login and no CAPTCHA are used.
* ICAR-ATARI Zone VIII, Pune (official): the KVK telephone directory PDF, retrieved through the
  Internet Archive because the official host did not resolve on the retrieval date.

Design: thin HTTP helpers that cache every raw response under ``data/raw_external/geo`` with a
``.meta.json`` sidecar (URL, retrieval time, SHA-256), and pure functions that turn cached payloads into
normalised records. Nothing here invents a name, a coordinate or a phone number: if a value cannot be
sourced it is left empty (or the record is dropped) and the gap is counted in the build report.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import logging
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import DATA_DIR, REPO_ROOT, get_settings

log = logging.getLogger("fasalalert.foundry.geo")

RAW_DIR = DATA_DIR / "raw_external" / "geo"
OUT_DIR = DATA_DIR / "geo"
WEB_GEO_DIR = REPO_ROOT / "apps" / "web" / "public" / "geo"

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/IND/{level}/"
OVERPASS_FALLBACKS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
AGMARKNET_API = "https://api.agmarknet.gov.in/v1/"
AGMARKNET_ORIGIN = "https://agmarknet.gov.in"
ATARI_KVK_PDF = "https://ataripune.icar.gov.in/PDF/KVK%20Telephone%20list%20new.pdf"
ATARI_KVK_PDF_SNAPSHOT = "20240305162150"  # Internet Archive capture of the official PDF
ATARI_KVK_PAGE = "https://ataripune.icar.gov.in/kvks-of-icar-atari.php"  # lists the directory PDF

MAHARASHTRA_QID = "Q1191"
DISTRICT_OF_INDIA_QID = "Q1149652"
TALUKA_OF_MAHARASHTRA_QID = "Q13119795"
EXPECTED_DISTRICTS = 36

LICENCES = {
    "wikidata": "CC0 1.0 (Wikidata)",
    "geoboundaries_adm2": "ODbL 1.0 (geoBoundaries gbOpen IND ADM2; source Pathways Data Pvt. Ltd., lgdirectory.gov.in)",
    "geoboundaries_adm3": "ODbL 1.0 (geoBoundaries gbOpen IND ADM3; source Pathways Data Pvt. Ltd., lgdirectory.gov.in)",
    "geoboundaries_adm1": "CC BY 2.5 IN (geoBoundaries gbOpen IND ADM1; source DataMeet India community)",
    "osm": "ODbL 1.0 (© OpenStreetMap contributors)",
    "agmarknet": "Government of India open data (AGMARKNET, Directorate of Marketing & Inspection)",
    "atari": "Official ICAR-ATARI Zone VIII, Pune publication (government information, quoted for contact purposes)",
}

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")


# =====================================================================================================
# HTTP and cache helpers
# =====================================================================================================
class SourceUnavailable(RuntimeError):
    """A source could not be fetched and no cached copy exists (or offline mode forbids fetching)."""


def user_agent() -> str:
    return f"{get_settings().http_user_agent} geo-seed (Maharashtra reference data)"


_last_call: dict[str, float] = {}


def _polite_wait(url: str, min_interval: float) -> None:
    host = urlparse(url).netloc
    wait = _last_call.get(host, 0.0) + min_interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ConnectTimeout | httpx.ConnectError):
        return False  # host unreachable: fail fast so the caller can try a mirror
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(4), wait=wait_exponential(multiplier=3, max=60),
       reraise=True)
def _request(method: str, url: str, *, params: dict | None = None, data: dict | None = None,
             json_body: Any = None, headers: dict | None = None, timeout: float = 120.0,
             min_interval: float = 1.0) -> httpx.Response:
    _polite_wait(url, min_interval)
    hdrs = {"User-Agent": user_agent()} | (headers or {})
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=20.0), headers=hdrs, follow_redirects=True) as c:
        r = c.request(method, url, params=params, data=data, json=json_body)
        r.raise_for_status()
        return r


def meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def read_meta(path: Path) -> dict:
    mp = meta_path(path)
    return json.loads(mp.read_text()) if mp.exists() else {}


def cached_fetch(url: str, dest: Path, *, method: str = "GET", params: dict | None = None,
                 data: dict | None = None, json_body: Any = None, headers: dict | None = None,
                 refresh: bool = False, offline: bool = False, timeout: float = 120.0,
                 min_interval: float = 1.0, validate: Any = None, note: str | None = None) -> Path:
    """Return ``dest``, downloading it first unless a cached copy exists. Writes a provenance sidecar."""
    if dest.exists() and not refresh:
        return dest
    if offline:
        raise SourceUnavailable(f"offline and no cached copy of {url} at {dest}")
    r = _request(method, url, params=params, data=data, json_body=json_body, headers=headers, timeout=timeout,
                 min_interval=min_interval)
    body = r.content
    if validate is not None:
        validate(body)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    meta = {"url": str(r.url), "method": method, "params": params, "request_body": data or json_body,
            "status": r.status_code, "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "user_agent": user_agent()}
    if note:
        meta["note"] = note
    meta_path(dest).write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return dest


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Wikidata
def sparql(name: str, query: str, *, refresh: bool = False, offline: bool = False) -> dict:
    dest = RAW_DIR / "wikidata" / f"{name}.json"

    def _check(body: bytes) -> None:
        json.loads(body)["results"]["bindings"]  # raises on a WDQS error page

    cached_fetch(WIKIDATA_SPARQL, dest, method="POST", data={"query": query, "format": "json"},
                 headers={"Accept": "application/sparql-results+json"}, refresh=refresh, offline=offline,
                 timeout=180, min_interval=2.0, validate=_check)
    return load_json(dest)


def sparql_rows(payload: dict) -> list[dict[str, str]]:
    return [{k: v["value"] for k, v in b.items()} for b in payload["results"]["bindings"]]


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- Overpass
_dead_endpoints: set[str] = set()


def overpass(name: str, query: str, *, refresh: bool = False, offline: bool = False) -> dict:
    """Run an Overpass query against the configured endpoint, then public mirrors, caching the result."""
    dest = RAW_DIR / "osm" / f"{name}.json"
    if dest.exists() and not refresh:
        return load_json(dest)
    if offline:
        raise SourceUnavailable(f"offline and no cached Overpass result {dest}")

    def _check(body: bytes) -> None:
        d = json.loads(body)
        if "elements" not in d or "runtime error" in str(d.get("remark", "")):
            raise ValueError(f"Overpass error: {d.get('remark')}")

    errors = []
    endpoints = [get_settings().overpass_url, *[u for u in OVERPASS_FALLBACKS if u != get_settings().overpass_url]]
    for attempt in range(4):
        for ep in endpoints:
            if ep in _dead_endpoints:
                continue
            try:
                cached_fetch(ep, dest, method="POST", data={"data": query}, refresh=True, timeout=240,
                             min_interval=2.0, validate=_check)
                return load_json(dest)
            except (httpx.ConnectTimeout, httpx.ConnectError) as e:
                _dead_endpoints.add(ep)  # unreachable from this network; skip it for the rest of the run
                errors.append(f"{ep}: unreachable ({type(e).__name__})")
            except Exception as e:  # noqa: BLE001 - busy mirror or error payload: try the next one
                errors.append(f"{ep}: {type(e).__name__}: {str(e)[:120]}")
                log.warning("overpass %s failed on %s: %s", name, ep, e)
        time.sleep(15 * (attempt + 1))
    raise SourceUnavailable(f"Overpass query {name} failed on every endpoint: {errors[-3:]}")


# ---------------------------------------------------------------- AGMARKNET 2.0 (public endpoints only)
def agmarknet(path: str, name: str, *, refresh: bool = False, offline: bool = False) -> Any:
    dest = RAW_DIR / "agmarknet" / f"{name}.json"

    def _check(body: bytes) -> None:
        d = json.loads(body)
        if isinstance(d, dict) and d.get("code") == "TOKEN_OR_CAPTCHA_REQUIRED":
            raise ValueError("endpoint is CAPTCHA-gated; not used")

    cached_fetch(AGMARKNET_API + path, dest, headers={"Origin": AGMARKNET_ORIGIN, "Referer": AGMARKNET_ORIGIN + "/",
                                                       "Accept": "application/json"},
                 refresh=refresh, offline=offline, min_interval=1.5, validate=_check)
    return load_json(dest)


# =====================================================================================================
# Text helpers
# =====================================================================================================
def is_devanagari(s: str | None) -> bool:
    """True when the string has Devanagari letters and no Latin letters."""
    return bool(s) and bool(DEVANAGARI.search(s)) and not LATIN.search(s)


def is_latin(s: str | None) -> bool:
    return bool(s) and bool(LATIN.search(s)) and not DEVANAGARI.search(s)


def clean(s: str | None) -> str:
    """Normalise whitespace and Unicode (NFC); drops zero-width joiners that break matching."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s).replace("‌", "").replace("‍", "").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def match_key(s: str) -> str:
    """Loose ASCII key for name matching across sources (case, punctuation and spacing removed)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


_SUFFIXES = {
    "en": (r"\s+(district|taluka|tehsil|taluk|subdistrict)$",),
    "mr": (r"\s+(जिल्हा|ज़िल्हा|तालुका|तहसील)$",),
    "hi": (r"\s+(जिला|ज़िला|ज़िल्हा|जिल्हा|तालुका|तहसील|तालुक|तालुक़ा)$",),
}


def strip_admin_suffix(label: str | None, lang: str) -> str:
    """'Nashik district' -> 'Nashik', 'नाशिक जिल्हा' -> 'नाशिक', and drop ', Maharashtra' style qualifiers."""
    s = clean(label)
    # Wikipedia disambiguation: "कर्जत तालुका (अहिल्यानगर)", "Khed taluka (Pune)"
    s = re.sub(r"\s+(तालुका|तहसील|तालुक|जिल्हा|जिला|taluka|tehsil|district)\s*\([^)]*\)$", "", s, flags=re.I)
    s = re.sub(r",\s*(Maharashtra|महाराष्ट्र|.*जिल्हा|.*जिला)$", "", s, flags=re.I)
    s = re.sub(r"\s*\((बीड|.*जिल्हा|.*जिला|Maharashtra|महाराष्ट्र)\)$", "", s)
    for pat in _SUFFIXES[lang]:
        s = re.sub(pat, "", s, flags=re.I)
    return s.strip()


def _split(v: str | None) -> list[str]:
    return [clean(x) for x in (v or "").split("|") if clean(x)]


# =====================================================================================================
# geoBoundaries
# =====================================================================================================
def geoboundaries(level: str, *, refresh: bool = False, offline: bool = False) -> tuple[dict, dict]:
    """(metadata, FeatureCollection) for gbOpen IND at ADM1/ADM2/ADM3. The licence comes from the metadata."""
    d = RAW_DIR / "geoboundaries"
    meta_file = cached_fetch(GEOBOUNDARIES_API.format(level=level), d / f"IND_{level}.api.json",
                             refresh=refresh, offline=offline)
    meta = load_json(meta_file)
    gj = cached_fetch(meta["gjDownloadURL"], d / f"IND_{level}.geojson", refresh=refresh, offline=offline,
                      timeout=600)
    return meta, load_json(gj)


def maharashtra_polygon(adm1: dict):
    from shapely.geometry import shape

    feats = [f for f in adm1["features"] if f["properties"].get("shapeISO") == "IN-MH"]
    if len(feats) != 1:
        raise ValueError(f"expected one IN-MH feature in ADM1, found {len(feats)}")
    return shape(feats[0]["geometry"]).buffer(0)


def features_in(fc: dict, region, min_overlap: float = 0.5) -> list[dict]:
    """Features whose area lies mostly (>= min_overlap) inside ``region``; adds 'overlap' to properties."""
    from shapely.geometry import shape
    from shapely.prepared import prep

    pr = prep(region)
    out = []
    for f in fc["features"]:
        g = shape(f["geometry"])
        if not pr.intersects(g):
            continue
        g = g.buffer(0)
        frac = g.intersection(region).area / g.area if g.area else 0.0
        if frac >= min_overlap:
            out.append({"properties": dict(f["properties"], overlap=round(frac, 4)), "geometry": g})
    return out


# =====================================================================================================
# OpenStreetMap settlements (Overpass, 1-degree tiles so each request stays small)
# =====================================================================================================
PLACE_TYPES_VILLAGE = ("village", "hamlet", "town")
PLACE_TYPES_GEOCODE = ("city", "town", "village", "hamlet", "suburb")


def osm_tiles(region, step: float = 1.0) -> list[tuple[float, float, float, float]]:
    from shapely.geometry import box

    minx, miny, maxx, maxy = region.bounds
    tiles = []
    lat = math.floor(miny)
    while lat < maxy:
        lon = math.floor(minx)
        while lon < maxx:
            b = (lat, lon, lat + step, lon + step)
            if box(lon, lat, lon + step, lat + step).intersects(region.buffer(0.05)):
                tiles.append(b)
            lon += step
        lat += step
    return tiles


def fetch_osm_places(region, *, refresh: bool = False, offline: bool = False) -> list[dict]:
    """All OSM place nodes of PLACE_TYPES_GEOCODE in tiles covering ``region`` (deduplicated by node id)."""
    pattern = "|".join(PLACE_TYPES_GEOCODE)
    seen: dict[int, dict] = {}
    for s, w, n, e in osm_tiles(region):
        name = f"places_{s:+05.1f}_{w:+06.1f}".replace("+", "p").replace("-", "m")
        q = f'[out:json][timeout:180];node["place"~"^({pattern})$"]({s},{w},{n},{e});out;'
        data = overpass(name, q, refresh=refresh, offline=offline)
        for el in data["elements"]:
            seen[el["id"]] = el
    return list(seen.values())


def fetch_osm_admin_names(region, *, refresh: bool = False, offline: bool = False) -> dict[str, dict[str, str]]:
    """{Wikidata QID: {'mr': name:mr, 'hi': name:hi}} from OSM district/taluka boundary relations (tags only)."""
    minx, miny, maxx, maxy = region.bounds
    q = (f'[out:json][timeout:120];rel["boundary"="administrative"]["admin_level"~"^(5|6)$"]["wikidata"]'
         f'({miny:.3f},{minx:.3f},{maxy:.3f},{maxx:.3f});out tags;')
    out = {}
    for el in overpass("admin_boundaries_l5_l6_tags", q, refresh=refresh, offline=offline)["elements"]:
        t = el.get("tags", {})
        out[t["wikidata"]] = {"mr": clean(t.get("name:mr")), "hi": clean(t.get("name:hi")), "osm_id": f"relation/{el['id']}"}
    return out


def osm_snapshot_dates() -> list[str]:
    out = set()
    for p in sorted((RAW_DIR / "osm").glob("places_*.json")):
        try:
            out.add(load_json(p).get("osm3s", {}).get("timestamp_osm_base", ""))
        except (OSError, ValueError):
            continue
    return sorted(x for x in out if x)


# =====================================================================================================
# Wikidata: districts and talukas
# =====================================================================================================
_LABEL_FIELDS = """
  OPTIONAL { ?X rdfs:label ?en_ FILTER(lang(?en_)="en") }
  OPTIONAL { ?X rdfs:label ?mr_ FILTER(lang(?mr_)="mr") }
  OPTIONAL { ?X rdfs:label ?hi_ FILTER(lang(?hi_)="hi") }
  OPTIONAL { ?X skos:altLabel ?aen FILTER(lang(?aen)="en") }
  OPTIONAL { ?X skos:altLabel ?amr FILTER(lang(?amr)="mr") }
  OPTIONAL { ?X skos:altLabel ?ahi FILTER(lang(?ahi)="hi") }
  OPTIONAL { ?smr schema:about ?X ; schema:isPartOf <https://mr.wikipedia.org/> ; schema:name ?mrwiki_ }
  OPTIONAL { ?shi schema:about ?X ; schema:isPartOf <https://hi.wikipedia.org/> ; schema:name ?hiwiki_ }
  OPTIONAL { ?X wdt:P625 ?coord_ }
  OPTIONAL { ?X wdt:P576 ?end_ }
"""
_LABEL_SELECT = """(SAMPLE(?en_) AS ?en) (SAMPLE(?mr_) AS ?mr) (SAMPLE(?hi_) AS ?hi)
  (GROUP_CONCAT(DISTINCT ?aen; separator="|") AS ?alias_en) (GROUP_CONCAT(DISTINCT ?amr; separator="|") AS ?alias_mr)
  (GROUP_CONCAT(DISTINCT ?ahi; separator="|") AS ?alias_hi) (SAMPLE(?mrwiki_) AS ?mrwiki) (SAMPLE(?hiwiki_) AS ?hiwiki)
  (GROUP_CONCAT(DISTINCT STR(?coord_); separator="|") AS ?coords) (SAMPLE(?end_) AS ?end)"""

DISTRICTS_QUERY = f"""
SELECT ?X (SAMPLE(?lgd_) AS ?lgd) {_LABEL_SELECT} WHERE {{
  {{ ?X wdt:P131 wd:{MAHARASHTRA_QID} . }} UNION {{ ?div wdt:P131 wd:{MAHARASHTRA_QID} . ?X wdt:P131 ?div . }}
  ?X wdt:P31 wd:{DISTRICT_OF_INDIA_QID} .
  OPTIONAL {{ ?X wdt:P12746 ?lgd_ }}
  {_LABEL_FIELDS}
}} GROUP BY ?X
"""

TALUKAS_QUERY = f"""
SELECT ?X (GROUP_CONCAT(DISTINCT STR(?d); separator="|") AS ?districts) (SAMPLE(?lgd_) AS ?lgd) {_LABEL_SELECT}
WHERE {{
  ?X wdt:P31 wd:{TALUKA_OF_MAHARASHTRA_QID} .
  ?X wdt:P131 ?d . ?d wdt:P12746 ?dl .
  OPTIONAL {{ ?X wdt:P12748 ?lgd_ }}
  {_LABEL_FIELDS}
}} GROUP BY ?X
"""

# Districts renamed by the Government of Maharashtra whose Wikidata *label* still carries the former name
# in some language. Each value must already exist on the item (label, alias or sitelink); the build fails
# otherwise, so this table selects among Wikidata strings and never introduces a new one.
# 'hi': 'mr' means no Wikidata Hindi string carries the full current name, so the current Marathi
# (Devanagari) name is used for Hindi and flagged as a fallback.
DISTRICT_CURRENT_NAMES: dict[str, dict[str, str]] = {
    "Q592942": {"en": "Chhatrapati Sambhajinagar district", "mr": "छत्रपती संभाजीनगर जिल्हा", "hi": "mr",
                "why": "Aurangabad district renamed Chhatrapati Sambhajinagar (Govt of Maharashtra, 2023)"},
    "Q1647186": {"en": "Dharashiv district", "mr": "धाराशिव जिल्हा", "hi": "धाराशिव जिला",
                 "why": "Osmanabad district renamed Dharashiv (Govt of Maharashtra, 2023)"},
    "Q401744": {"en": "Ahilyanagar district", "mr": "अहिल्यानगर जिल्हा", "hi": "अहिल्यानगर जिला",
                "why": "Ahmednagar district renamed Ahilyanagar (Govt of Maharashtra, 2024)"},
}


# Talukas renamed with their districts whose Wikidata English label is still the former name. The value
# must be one of the item's own English aliases (checked at build time).
TALUKA_CURRENT_NAMES: dict[str, str] = {
    "Q13116206": "Chhatrapati Sambhajinagar",  # formerly Aurangabad taluka
    "Q11114967": "Dharashiv",                  # formerly Osmanabad taluka
}


def _parse_coords(s: str) -> list[tuple[float, float]]:
    out = []
    for part in _split(s):
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", part)
        if m:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def _all_strings(row: dict, lang: str) -> list[str]:
    vals = [row.get(lang, "")] + _split(row.get(f"alias_{lang}"))
    if lang in ("mr", "hi"):
        vals.append(row.get(f"{lang}wiki", ""))
    return [clean(v) for v in vals if clean(v)]


def _choose(row: dict, lang: str, preferred: list[str]) -> tuple[str, str]:
    """Pick the first non-empty candidate (already suffix-stripped) and say where it came from."""
    for src in preferred:
        v = strip_admin_suffix(row.get(src, ""), lang)
        if v:
            return v, f"wikidata:{src}"
    return "", ""


def normalise_wikidata_districts(payload: dict) -> tuple[list[dict], list[dict]]:
    """Official Maharashtra districts = items that carry an LGD district code (P12746) and no end date."""
    rows = sparql_rows(payload)
    out, excluded = [], []
    for r in rows:
        q = qid(r["X"])
        if not r.get("lgd") or r.get("end"):
            excluded.append({"qid": q, "label": r.get("en"), "reason": "no LGD district code" if not r.get("lgd")
                             else "dissolved"})
            continue
        en, en_src = _choose(r, "en", ["en"])
        mr, mr_src = _choose(r, "mr", ["mrwiki", "mr"])
        hi, hi_src = _choose(r, "hi", ["hi", "hiwiki"])
        override = DISTRICT_CURRENT_NAMES.get(q)
        if override:
            for lang in ("en", "mr", "hi"):
                want = override[lang]
                if lang == "hi" and want == "mr":
                    continue
                if want not in _all_strings(r, lang):
                    raise ValueError(f"{q}: override {lang}={want!r} is not a Wikidata label/alias/sitelink")
            en, en_src = strip_admin_suffix(override["en"], "en"), "wikidata:alias (current official name)"
            mr, mr_src = strip_admin_suffix(override["mr"], "mr"), "wikidata:label/alias/mrwiki (current name)"
            if override["hi"] == "mr":
                hi, hi_src = mr, "mr_fallback (no Wikidata Hindi string carries the full current name)"
            else:
                hi, hi_src = strip_admin_suffix(override["hi"], "hi"), "wikidata:hi label/alias (current name)"
        if not hi and mr:
            hi, hi_src = mr, "mr_fallback"
        names = {"en": en, "mr": mr, "hi": hi}
        aliases = {}
        for lang in ("en", "mr", "hi"):
            vals = {strip_admin_suffix(v, lang) for v in _all_strings(r, lang)}
            vals |= {strip_admin_suffix(r.get("hiwiki", ""), lang)} if lang == "hi" else set()
            aliases[lang] = sorted(v for v in vals if v and v != names[lang])
        out.append({
            "qid": q, "lgd_code": int(r["lgd"]), "code": slugify(en), "name_en": en, "name_mr": mr, "name_hi": hi,
            "name_sources": {"en": en_src, "mr": mr_src, "hi": hi_src}, "aliases": aliases,
            "renamed": override["why"] if override else None,
            "wikidata_coords": _parse_coords(r.get("coords", "")),
            "source_url": f"https://www.wikidata.org/wiki/{q}",
        })
    out.sort(key=lambda d: d["code"])
    codes = Counter(d["code"] for d in out)
    if any(n > 1 for n in codes.values()):
        raise ValueError(f"duplicate district codes: {codes}")
    return out, excluded


def normalise_wikidata_talukas(payload: dict, districts: list[dict],
                               osm_names: dict[str, dict[str, str]] | None = None) -> tuple[list[dict], list[dict]]:
    """Talukas from Wikidata; ``osm_names`` ({QID: {'mr','hi'}}) from OSM admin boundaries fills gaps."""
    by_qid = {d["qid"]: d for d in districts}
    out, excluded = [], []
    for r in sparql_rows(payload):
        q = qid(r["X"])
        dq = [qid(x) for x in _split(r.get("districts")) if qid(x) in by_qid]
        if r.get("end"):
            excluded.append({"qid": q, "label": r.get("en"), "reason": "dissolved"})
            continue
        if len(dq) != 1:
            excluded.append({"qid": q, "label": r.get("en"), "reason": f"located in {len(dq)} official districts"})
            continue
        d = by_qid[dq[0]]
        en, en_src = _choose(r, "en", ["en"])
        mr, mr_src = _choose(r, "mr", ["mrwiki", "mr"])
        hi, hi_src = _choose(r, "hi", ["hi", "hiwiki"])
        if q in TALUKA_CURRENT_NAMES:
            want = TALUKA_CURRENT_NAMES[q]
            if want not in {strip_admin_suffix(v, "en") for v in _all_strings(r, "en")}:
                raise ValueError(f"{q}: taluka override {want!r} is not a Wikidata English label/alias")
            en, en_src = want, "wikidata:alias (current official name)"
        osm = (osm_names or {}).get(q, {})
        if not is_devanagari(mr) and is_devanagari(osm.get("mr")):
            mr, mr_src = strip_admin_suffix(osm["mr"], "mr"), "osm:name:mr (admin boundary with wikidata tag)"
        if not is_devanagari(hi) and is_devanagari(osm.get("hi")):
            hi, hi_src = strip_admin_suffix(osm["hi"], "hi"), "osm:name:hi (admin boundary with wikidata tag)"
        mr0, hi0 = mr, hi
        if not mr:
            mr, mr_src = (hi0, "hi_fallback (Devanagari Hindi label)") if is_devanagari(hi0) else (en, "latin_fallback")
        if not hi:
            hi, hi_src = (mr0, "mr_fallback") if is_devanagari(mr0) else (en, "latin_fallback")
        out.append({
            "qid": q, "lgd_code": int(r["lgd"]) if r.get("lgd") else None, "district_code": d["code"],
            "district_qid": d["qid"], "name_en": en, "name_mr": mr, "name_hi": hi,
            "name_sources": {"en": en_src, "mr": mr_src, "hi": hi_src},
            "aliases": {lang: sorted({strip_admin_suffix(v, lang) for v in _all_strings(r, lang)} - {"", {"en": en,
                                     "mr": mr, "hi": hi}[lang]}) for lang in ("en", "mr", "hi")},
            "wikidata_coords": _parse_coords(r.get("coords", "")),
            "source_url": f"https://www.wikidata.org/wiki/{q}",
        })
    return out, excluded


# =====================================================================================================
# Matching geoBoundaries polygons to Wikidata districts and talukas
# =====================================================================================================
# geoBoundaries ADM2 (2021) shapeName -> Wikidata QID, for every name that is not the current official
# English name. Reviewed by hand against LGD/Census spellings; the build asserts a 1:1 match of 36.
GB_ADM2_ALIASES: dict[str, str] = {
    "Ahmadnagar": "Q401744",   # Ahilyanagar (renamed 2024)
    "Aurangabad": "Q592942",   # Chhatrapati Sambhajinagar (renamed 2023)
    "Osmanabad": "Q1647186",   # Dharashiv (renamed 2023)
    "Bid": "Q814037",          # Beed (Census spelling)
    "Buldana": "Q47929",       # Buldhana (Census spelling)
    "Gondiya": "Q1917227",     # Gondia (Census spelling)
    "Raigarh": "Q2019683",     # Raigad (Census spelling)
    "Mumbai": "Q2341660",      # Mumbai City district
}


def match_districts_to_adm2(districts: list[dict], adm2_mh: list[dict]) -> dict[str, dict]:
    """{district code: ADM2 feature}. Exact key match on the official name, otherwise GB_ADM2_ALIASES."""
    by_qid = {d["qid"]: d for d in districts}
    by_key = {match_key(d["name_en"]): d for d in districts}
    out: dict[str, dict] = {}
    unmatched = []
    for f in adm2_mh:
        name = f["properties"]["shapeName"]
        d = by_qid.get(GB_ADM2_ALIASES.get(name, "")) or by_key.get(match_key(name))
        if d is None:
            unmatched.append(name)
            continue
        if d["code"] in out:
            raise ValueError(f"two ADM2 features match {d['code']}: {out[d['code']]['properties']['shapeName']}, {name}")
        out[d["code"]] = f
    missing = sorted(set(d["code"] for d in districts) - set(out))
    if unmatched or missing:
        raise ValueError(f"ADM2 match not 1:1: unmatched features {unmatched}, districts without polygon {missing}")
    return out


def point_in_poly(geom, x: float, y: float) -> bool:
    from shapely.geometry import Point

    return geom.covers(Point(x, y))


def inner_centroid(geom) -> tuple[float, float]:
    c = geom.centroid
    if not geom.covers(c):
        c = geom.representative_point()
    return round(c.x, 6), round(c.y, 6)


# geoBoundaries ADM3 (2018, LGD-derived) sub-district name -> Wikidata taluka English name, per district,
# for spellings that differ. Reviewed by hand; every other ADM3 unit matches on the normalised name.
GB_ADM3_ALIASES: dict[tuple[str, str], str] = {
    ("ahilyanagar", "Rahta"): "Rahata",
    ("ahilyanagar", "Akola"): "Akole",
    ("amravati", "Teosa"): "Tiosa",
    ("beed", "Manjlegaon"): "Majalgaon",
    ("beed", "Bid"): "Beed",
    ("chandrapur", "Nagbhir"): "Nagbhid",
    ("hingoli", "Basmath"): "Vasmath",
    ("jalna", "Jafferabad"): "Jafrabad",
    ("kolhapur", "Bavda"): "Gaganbawada",
    ("nanded", "Mahoor"): "Mahur",
    ("palghar", "Vikramgad"): "Vikramgadh",
    ("palghar", "Vada"): "Wada",
    ("parbhani", "Sailu"): "Selu",
    ("pune", "Purandhar"): "Purandar",
    ("satara", "Jaoli"): "Jawali",
}
# ADM3 units that cover a whole district for which Wikidata lists no taluka. Mumbai City district has
# no talukas in Wikidata (Maharashtra's 358 talukas), but LGD (via geoBoundaries ADM3) carries one
# sub-district 'Mumbai' covering it. It is kept as a district-equivalent unit so the cascading
# district -> taluka -> village picker never dead-ends; names come from the district's Wikidata item.
GB_ADM3_DISTRICT_EQUIVALENT = {("mumbai-city", "Mumbai")}
# ADM3 units that merge several Wikidata talukas (no split polygon is available).
GB_ADM3_MERGED = {("mumbai-suburban", "Mumbai Suburban")}


def wikidata_settlements(names: Iterable[str], *, refresh: bool = False, offline: bool = False) -> list[dict]:
    """Wikidata items whose English label is one of ``names`` and that have coordinates (CC0)."""
    names = sorted({n for n in names if n})
    if not names:
        return []
    tag = hashlib.sha1("|".join(names).encode()).hexdigest()[:10]
    vals = " ".join(json.dumps(n) + "@en" for n in names)
    q = f"SELECT ?item ?name ?coord WHERE {{ VALUES ?name {{ {vals} }} ?item rdfs:label ?name ; wdt:P625 ?coord . }}"
    out = []
    for r in sparql_rows(sparql(f"settlements_{tag}", q, refresh=refresh, offline=offline)):
        for x, y in _parse_coords(r.get("coord", "")):
            out.append({"qid": qid(r["item"]), "name": r["name"], "lon": x, "lat": y})
    return out


def build_talukas(talukas: list[dict], districts: list[dict], district_feats: dict[str, dict],
                  adm3_mh: list[dict], osm_places: list[dict],
                  wd_settlements: list[dict] | None = None) -> tuple[list[dict], dict[str, Any], dict]:
    """Attach ADM3 polygons and centroids to Wikidata talukas.

    Returns (talukas, polygons {taluka code: geometry | None}, report). Centroid priority: ADM3 polygon
    centroid; Wikidata P625; the OSM settlement node of the same name inside the district (the taluka
    headquarters, which talukas are named after). A taluka with none of these is dropped and reported.
    """
    dist_by_code = {d["code"]: d for d in districts}
    by_district: dict[str, list[dict]] = defaultdict(list)
    for t in talukas:
        by_district[t["district_code"]].append(t)
    polys: dict[str, Any] = {}
    report: dict[str, Any] = {"adm3_in_maharashtra": len(adm3_mh), "adm3_alias_matches": [], "merged_units": [],
                              "district_equivalent_units": [], "unmatched_adm3": [], "dropped": []}
    tq: dict[str, dict] = {}
    extra: list[dict] = []
    for f in adm3_mh:
        rp = f["geometry"].representative_point()
        dcs = [c for c, df in district_feats.items() if df["geometry"].covers(rp)]
        if not dcs:
            report["unmatched_adm3"].append(f["properties"]["shapeName"] + " (outside every district)")
            continue
        dc, name = dcs[0], f["properties"]["shapeName"]
        if (dc, name) in GB_ADM3_MERGED:
            report["merged_units"].append(f"{dc}/{name}")
            continue
        if (dc, name) in GB_ADM3_DISTRICT_EQUIVALENT:
            d = dist_by_code[dc]
            t = {"qid": None, "lgd_code": None, "district_code": dc, "district_qid": d["qid"], "name_en": d["name_en"],
                 "name_mr": d["name_mr"], "name_hi": d["name_hi"],
                 "name_sources": {lang: f"district names ({d['name_sources'][lang]}); geoBoundaries ADM3 '{name}'"
                                  for lang in ("en", "mr", "hi")},
                 "aliases": {"en": [name], "mr": [], "hi": []}, "wikidata_coords": [],
                 "source_url": "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM3/",
                 "kind": "district-equivalent sub-district (no Wikidata taluka)"}
            extra.append(t)
            t["adm3_name"], t["_geom"] = name, f["geometry"]
            report["district_equivalent_units"].append(f"{dc}/{name}")
            continue
        want = GB_ADM3_ALIASES.get((dc, name))
        cands = by_district.get(dc, [])
        if want:
            hit = [t for t in cands if t["name_en"] == want]
            report["adm3_alias_matches"].append(f"{dc}: {name} -> {want}")
        else:
            k = match_key(name)
            hit = [t for t in cands if match_key(t["name_en"]) == k or k in {match_key(a) for a in t["aliases"]["en"]}]
        if len(hit) != 1:
            report["unmatched_adm3"].append(f"{dc}/{name} ({len(hit)} candidates)")
            continue
        if hit[0]["qid"] in tq:
            raise ValueError(f"two ADM3 units match taluka {hit[0]['name_en']}")
        hit[0]["adm3_name"], hit[0]["_geom"] = name, f["geometry"]
        tq[hit[0]["qid"]] = hit[0]

    settlements = [e for e in osm_places if e.get("tags", {}).get("place") in ("city", "town", "suburb", "village")]
    out = []
    for t in talukas + extra:
        dc = t["district_code"]
        dgeom = district_feats[dc]["geometry"]
        geom = t.pop("_geom", None)
        if geom is not None:
            lon, lat = inner_centroid(geom)
            t["centroid_source"] = f"geoboundaries:ADM3 '{t['adm3_name']}' polygon centroid"
        elif any(point_in_poly(dgeom, x, y) for x, y in t["wikidata_coords"]):
            lon, lat = next((x, y) for x, y in t["wikidata_coords"] if point_in_poly(dgeom, x, y))
            t["centroid_source"] = "wikidata:P625"
        else:
            keys = {match_key(t["name_en"])} | {match_key(a) for a in t["aliases"]["en"]}
            hq = [e for e in settlements if match_key(e["tags"].get("name:en") or e["tags"].get("name", "")) in keys
                  and point_in_poly(dgeom, e["lon"], e["lat"])]
            rank = ("city", "town", "suburb", "village")
            hq.sort(key=lambda e: rank.index(e["tags"]["place"]))
            top = [e for e in hq if e["tags"]["place"] == hq[0]["tags"]["place"]] if hq else []
            wd = sorted((w for w in (wd_settlements or []) if match_key(w["name"]) in keys
                         and point_in_poly(dgeom, w["lon"], w["lat"])), key=lambda w: (w["qid"], w["lon"], w["lat"]))
            if len(top) == 1:  # exactly one settlement of the best rank; otherwise ambiguous
                e = top[0]
                lon, lat = e["lon"], e["lat"]
                t["centroid_source"] = (f"osm:node/{e['id']} (place={e['tags']['place']} "
                                        f"'{e['tags'].get('name')}', taluka headquarters of the same name)")
            elif wd and len({w["qid"] for w in wd}) == 1:  # one Wikidata settlement of that name in the district
                lon, lat = wd[0]["lon"], wd[0]["lat"]
                t["centroid_source"] = (f"wikidata:{wd[0]['qid']} P625 (settlement '{wd[0]['name']}', taluka "
                                        "headquarters of the same name)")
            else:
                report["dropped"].append(f"{dc}/{t['name_en']}: no polygon, coordinate or HQ settlement")
                continue
        t["lon"], t["lat"] = round(lon, 6), round(lat, 6)
        t["code"] = f"{dc}-{slugify(t['name_en'])}"
        if geom is not None:
            polys[t["code"]] = geom
        out.append(t)
    codes = Counter(t["code"] for t in out)
    dup = [c for c, n in codes.items() if n > 1]
    if dup:
        raise ValueError(f"duplicate taluka codes {dup}")
    report["talukas"] = len(out)
    report["with_adm3_polygon"] = len(polys)
    def _kind(src: str) -> str:
        return ("geoboundaries ADM3 polygon centroid" if src.startswith("geoboundaries") else
                "wikidata P625" if src == "wikidata:P625" else
                "OSM HQ settlement node" if src.startswith("osm:") else "Wikidata HQ settlement P625")
    report["centroid_sources"] = dict(Counter(_kind(t["centroid_source"]) for t in out))
    out.sort(key=lambda t: t["code"])
    return out, polys, report


# =====================================================================================================
# Villages (OSM place nodes) with district and taluka assignment
# =====================================================================================================
def wikidata_labels(qids: Iterable[str], *, refresh: bool = False, offline: bool = False,
                    batch: int = 300) -> dict[str, dict[str, str]]:
    """Marathi and Hindi labels for Wikidata items referenced by OSM ``wikidata=*`` tags (CC0)."""
    ids = sorted({q for q in qids if re.fullmatch(r"Q\d+", q or "")}, key=lambda q: int(q[1:]))
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        tag = hashlib.sha1(" ".join(chunk).encode()).hexdigest()[:10]
        q = ("SELECT ?item ?mr ?hi WHERE { VALUES ?item { " + " ".join(f"wd:{x}" for x in chunk) + " } "
             'OPTIONAL { ?item rdfs:label ?mr FILTER(lang(?mr)="mr") } '
             'OPTIONAL { ?item rdfs:label ?hi FILTER(lang(?hi)="hi") } }')
        for r in sparql_rows(sparql(f"osm_item_labels_{tag}", q, refresh=refresh, offline=offline)):
            d = out.setdefault(qid(r["item"]), {})
            for lang in ("mr", "hi"):
                if r.get(lang):
                    d[lang] = clean(r[lang])
    return out


def _village_names(tags: dict, wd: dict[str, str]) -> dict[str, str] | None:
    name, n_en, n_mr, n_hi = (clean(tags.get(k)) for k in ("name", "name:en", "name:mr", "name:hi"))
    base = name or n_en or n_mr
    if not base:
        return None
    if is_latin(n_en):
        en, s_en = n_en, "osm:name:en"
    elif is_latin(name):
        en, s_en = name, "osm:name"
    else:
        en, s_en = base, "osm:name (no Latin-script name in OSM; copied as is)"
    wd_mr, wd_hi = clean(wd.get("mr")), clean(wd.get("hi"))
    if is_devanagari(n_mr):
        mr, s_mr = n_mr, "osm:name:mr"
    elif is_devanagari(wd_mr):
        mr, s_mr = strip_admin_suffix(wd_mr, "mr"), "wikidata:mr label (via osm wikidata tag)"
    elif is_devanagari(name):
        mr, s_mr = name, "osm:name (Devanagari)"
    else:
        mr, s_mr = en, "latin_fallback"
    if is_devanagari(n_hi):
        hi, s_hi = n_hi, "osm:name:hi"
    elif is_devanagari(wd_hi):
        hi, s_hi = strip_admin_suffix(wd_hi, "hi"), "wikidata:hi label (via osm wikidata tag)"
    elif is_devanagari(mr):
        hi, s_hi = mr, "mr_fallback"
    else:
        hi, s_hi = en, "latin_fallback"
    return {"name_en": en, "name_mr": mr, "name_hi": hi, "src_en": s_en, "src_mr": s_mr, "src_hi": s_hi}


def _flat_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    kx = 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon1 - lon2) * kx, (lat1 - lat2) * 110.57)


def build_villages(osm_places: list[dict], district_feats: dict[str, dict], talukas: list[dict],
                   taluka_polys: dict[str, Any], wd_labels: dict[str, dict[str, str]],
                   max_offshore_km: float = 1.0) -> tuple[list[dict], dict[str, Any]]:
    """Normalise OSM village/hamlet/town nodes and assign each to a district and a taluka.

    District: the district polygon that covers the node (nodes up to ``max_offshore_km`` outside every
    polygon, e.g. on the coast, go to the nearest district; others are outside Maharashtra and dropped).
    Taluka: the geoBoundaries ADM3 polygon of a taluka *of that district* that covers the node; where no
    such polygon exists (Mumbai Suburban's three talukas share one ADM3 unit, or slivers where ADM2 and
    ADM3 edges disagree), the nearest taluka centroid within the district. The nearest-centroid answer is
    also computed for every node so its error against the polygon answer can be measured.
    """
    from shapely import STRtree
    from shapely.geometry import Point

    dcodes = list(district_feats)
    dgeoms = [district_feats[c]["geometry"] for c in dcodes]
    dtree = STRtree(dgeoms)
    tcodes = list(taluka_polys)
    ttree = STRtree([taluka_polys[c] for c in tcodes])
    t_by_code = {t["code"]: t for t in talukas}
    t_by_district: dict[str, list[dict]] = defaultdict(list)
    for t in talukas:
        t_by_district[t["district_code"]].append(t)

    rep: Counter = Counter()
    rows, seen = [], set()
    for el in sorted(osm_places, key=lambda e: e["id"]):
        tags = el.get("tags", {})
        if tags.get("place") not in PLACE_TYPES_VILLAGE:
            continue
        rep["osm_nodes_considered"] += 1
        names = _village_names(tags, wd_labels.get(tags.get("wikidata", ""), {}))
        if names is None:
            rep["dropped_no_name"] += 1
            continue
        lon, lat = round(el["lon"], 7), round(el["lat"], 7)
        pt = Point(lon, lat)
        hits = [dcodes[i] for i in dtree.query(pt, predicate="covered_by")]
        if hits:
            dc, dmethod = hits[0], "polygon"
        else:
            i = dtree.nearest(pt)
            near = dcodes[int(i)]
            dist_km = district_feats[near]["geometry"].distance(pt) * 111.0
            if dist_km > max_offshore_km:
                rep["dropped_outside_maharashtra"] += 1
                continue
            dc, dmethod = near, f"nearest_district_within_{max_offshore_km:g}km"
            rep["district_nearest_fallback"] += 1
        cands = t_by_district.get(dc, [])
        if not cands:
            rep["dropped_district_without_taluka"] += 1
            continue
        nearest = min(cands, key=lambda t: _flat_km(lon, lat, t["lon"], t["lat"]))["code"]
        poly_hits = [tcodes[i] for i in ttree.query(pt, predicate="covered_by")]
        poly_hits = [c for c in poly_hits if t_by_code[c]["district_code"] == dc]
        if poly_hits:
            tc, tmethod = poly_hits[0], "adm3_polygon"
        else:
            tc, tmethod = nearest, "nearest_centroid"
        key = (names["name_en"], round(lat, 6), round(lon, 6))  # the seed's natural key
        if key in seen:
            rep["dropped_duplicate"] += 1
            continue
        seen.add(key)
        rows.append({"osm_id": f"node/{el['id']}", "place": tags["place"], **names, "lat": round(lat, 6),
                     "lon": round(lon, 6), "district_code": dc, "taluka_code": tc, "district_method": dmethod,
                     "taluka_method": tmethod, "nearest_centroid_taluka_code": nearest})
    rows.sort(key=lambda r: (r["district_code"], r["taluka_code"], r["name_en"], r["osm_id"]))
    poly_rows = [r for r in rows if r["taluka_method"] == "adm3_polygon"]
    agree = sum(r["taluka_code"] == r["nearest_centroid_taluka_code"] for r in poly_rows)
    report = dict(rep)
    report.update({
        "villages": len(rows),
        "by_place": dict(Counter(r["place"] for r in rows)),
        "taluka_method": dict(Counter(r["taluka_method"] for r in rows)),
        "nearest_centroid_vs_polygon": {
            "compared": len(poly_rows), "agree": agree,
            "disagreement_rate": round(1 - agree / len(poly_rows), 4) if poly_rows else None},
        "name_sources": {lang: dict(Counter(r[f"src_{lang}"] for r in rows)) for lang in ("en", "mr", "hi")},
        "per_district": dict(Counter(r["district_code"] for r in rows)),
    })
    return rows, report


VILLAGE_COLUMNS = ["osm_id", "place", "name_en", "name_mr", "name_hi", "src_en", "src_mr", "src_hi", "lat", "lon",
                   "district_code", "taluka_code", "district_method", "taluka_method", "nearest_centroid_taluka_code"]


def write_villages_csv(rows: list[dict], path: Path) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=VILLAGE_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode("utf-8"))


def read_villages_csv(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
    return rows


# =====================================================================================================
# AGMARKNET mandi markets
# =====================================================================================================
AGMARKNET_STATE = "Maharashtra"
APMC_CATEGORIES = ("Principal Market Yard", "Sub Market Yard")
# AGMARKNET 2.0 district names (Maharashtra) that are not the current official district name or one of
# its Wikidata aliases. Reviewed by hand; 'Bandra(E)' and 'Murum' are AGMARKNET's own district entries.
AGMARKNET_DISTRICT_ALIASES: dict[str, str] = {
    "Chattrapati Sambhajinagar": "chhatrapati-sambhajinagar",
    "Amarawati": "amravati",
    "Gondiya": "gondia",
    "Bandra(E)": "mumbai-suburban",
    "Murum": "dharashiv",          # Murum town, Umarga taluka, Dharashiv district
    "Mumbai": "mumbai-city",
}


# Markets whose AGMARKNET *address* puts the yard in a different settlement (and district) from the one
# in the market name: the Mumbai APMC yards are at Vashi, Navi Mumbai (Thane district) per AGMARKNET's
# own address field "Administrative Building, Sector 18, Vashi, Navi Mumbai. 400703".
MANDI_ADDRESS_PLACES: dict[str, tuple[str, str]] = {
    "APMC Mumbai": ("Vashi", "thane"),
    "Mumbai- Fruit Market": ("Vashi", "thane"),
    "Mumbai-Onion & Potato Market": ("Vashi", "thane"),
}


# AGMARKNET spellings of market towns -> the official taluka/town spelling used by Wikidata, geoBoundaries
# ADM3 and OSM (reviewed by hand; same district). The geocoder still requires exactly one OSM node of
# that name in the district.
MANDI_PLACE_ALIASES: dict[str, str] = {
    "Amarawati": "Amravati", "Amrawati": "Amravati", "Chandwad": "Chandvad", "Dound": "Daund", "Sinner": "Sinnar",
    "Kamthi": "Kamptee", "Varora": "Warora", "Varud": "Warud", "Vani": "Wani", "Savner": "Saoner", "Pavani": "Pauni",
    "Mangrulpeer": "Mangrulpir", "Newasa": "Nevasa", "Gevrai": "Georai", "Brahmpuri": "Brahmapuri",
    "Suragana": "Surgana", "Kalvan": "Kalwan", "Khultabad": "Khuldabad", "Fulmbri": "Phulambri", "Devala": "Deola",
    "Sengoan": "Sengaon", "Maregoan": "Maregaon", "Vadvani": "Wadwani", "Chikali": "Chikhli",
    "Parli Vaijnath": "Parli", "Kille Dharur": "Dharur", "Ahmedpur": "Ahmadpur", "Aatpadi": "Atpadi",
    "Sangola": "Sangole", "Savali": "Sawali", "Dhamngaon-Railway": "Dhamangaon Railway",
    "Barshi Takli": "Barshitakli", "ZariZamini": "Zari Jamani", "Devani": "Deoni", "Parshiwani": "Parseoni",
    "Bhusaval": "Bhusawal", "Kurdwadi": "Kurduvadi", "Jawala-Bajar": "Jawala Bazar",
}


def app_commodities() -> list[str]:
    """The six FasalAlert crops' AGMARKNET commodity names (packages/shared/crops.json)."""
    crops = load_json(REPO_ROOT / "packages" / "shared" / "crops.json")["crops"]
    return [c["agmarknet_commodity"] for c in crops.values()]


def fetch_agmarknet(*, refresh: bool = False, offline: bool = False) -> dict[str, Any]:
    """Public AGMARKNET 2.0 endpoints: all markets, all commodities, and the markets per commodity."""
    markets = agmarknet("dashboard-market-filter", "dashboard_market_filter", refresh=refresh, offline=offline)["data"]
    commodities: list[dict] = []
    page = 1
    while True:
        d = agmarknet(f"commodities?page={page}&page_size=500", f"commodities_p{page}", refresh=refresh, offline=offline)
        commodities += d["data"]
        if not d["pagination"].get("next_page"):
            break
        page += 1
    by_name = {c["cmdt_name"]: c for c in commodities}
    per_commodity = {}
    for name in app_commodities():
        c = by_name.get(name)
        if c is None:
            raise ValueError(f"AGMARKNET has no commodity named {name!r}")
        per_commodity[name] = {"commodity": c, "markets": agmarknet(f"list-comm/{c['id']}", f"list_comm_{c['id']}",
                                                                    refresh=refresh, offline=offline)["data"]}
    return {"markets": markets, "per_commodity": per_commodity}


def map_agmarknet_district(name: str, districts: list[dict]) -> str | None:
    n = clean(name)
    if n in AGMARKNET_DISTRICT_ALIASES:
        return AGMARKNET_DISTRICT_ALIASES[n]
    k = match_key(n)
    for d in districts:
        if k == match_key(d["name_en"]) or k in {match_key(a) for a in d["aliases"]["en"]}:
            return d["code"]
    return None


_MKT_NOISE = re.compile(
    r"\b(apmc|a\.p\.m\.c|market yard|market|yard|krushi utpanna bazar samiti|krishi utpanna bazar samiti|"
    r"sub ?market|f\s*&\s*v|fruit|frui|veg\.?|vegetable|grain|new|old|pvt\.?|ltd\.?)\b", re.I)


def market_place_candidates(name: str) -> list[tuple[str, str]]:
    """Place names a market is named after: [('sub', 'Dhad'), ('full', 'Buldhana Dhad'), ('main', 'Buldhana')]."""
    n = clean(name)
    out = []
    for inner in re.findall(r"\(([^)]*)\)", n):
        s = clean(_MKT_NOISE.sub(" ", inner)).strip(" -.,&")
        if s and len(s) > 2:
            out.append(("sub", s))
    main = clean(_MKT_NOISE.sub(" ", re.sub(r"\([^)]*\)", " ", n))).strip(" -.,&")
    if main and out:  # "APMC Jalgaon(Jamod)" is the town Jalgaon Jamod
        out.append(("full", f"{main} {out[-1][1]}"))
    if main:
        out.append(("main", main))
    return out


_PLACE_RANK = {"city": 0, "town": 1, "suburb": 2, "village": 3, "hamlet": 4}


def _place_keys(tags: dict) -> set[str]:
    vals = [tags.get(k, "") for k in ("name", "name:en", "alt_name", "old_name", "official_name", "alt_name:en")]
    return {match_key(x) for v in vals for x in v.split(";") if match_key(x)}


def geocode_market(name: str, district_code: str, places_by_district: dict[str, list[dict]],
                   fuzzy_min: float = 0.88, *, sub_yard: bool = True,
                   district_keys: set[str] | None = None) -> dict | None:
    """Settlement-level geocode: the OSM place node (inside the market's district) the market is named after.

    Exact match on a normalised name first (any place type; ties broken by place rank, and a tie within the
    top rank is ambiguous -> no geocode); then a conservative fuzzy match against towns and cities only.
    Returns None rather than guessing.
    """
    places = places_by_district.get(district_code, [])
    for role, cand in market_place_candidates(name):
        # "Buldhana(Dhad)" is Buldhana APMC's sub-yard at Dhad, but "APMC Ashti(Jalna)" only names the district:
        # a bracketed place is a location only for sub-yards and only when it is not a district name.
        if role == "sub" and (not sub_yard or match_key(cand) in (district_keys or set())):
            continue
        if cand in MANDI_PLACE_ALIASES:
            cand = MANDI_PLACE_ALIASES[cand]
        k = match_key(cand)
        exact = [p for p in places if k in p["_keys"]]
        if exact:
            exact.sort(key=lambda p: _PLACE_RANK[p["tags"]["place"]])
            top = [p for p in exact if p["tags"]["place"] == exact[0]["tags"]["place"]]
            if len(top) == 1:
                return _geo(top[0], cand, role, "exact")
            continue  # ambiguous at the top rank
        if len(k) < 5:
            continue
        scored = sorted(((max(SequenceMatcher(None, k, pk).ratio() for pk in p["_keys"]), p) for p in places
                         if p["tags"]["place"] in ("city", "town")), key=lambda x: -x[0])
        if scored and scored[0][0] >= fuzzy_min and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05):
            return _geo(scored[0][1], cand, role, f"fuzzy:{scored[0][0]:.2f}")
    return None


def _geo(p: dict, cand: str, role: str, how: str) -> dict:
    return {"lat": round(p["lat"], 6), "lon": round(p["lon"], 6),
            "geocode_source": (f"osm:node/{p['id']} place={p['tags']['place']} name='{p['tags'].get('name')}' "
                               f"matched '{cand}' ({'sub-yard location' if role == 'sub' else 'market town'}, "
                               f"{how}, settlement-level precision)")}


def build_mandis(agm: dict[str, Any], districts: list[dict], district_feats: dict[str, dict],
                 osm_places: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    from shapely import STRtree
    from shapely.geometry import Point

    mk = {m["id"]: m for m in agm["markets"]}
    dcodes = list(district_feats)
    tree = STRtree([district_feats[c]["geometry"] for c in dcodes])
    places_by_district: dict[str, list[dict]] = defaultdict(list)
    for e in osm_places:
        if e.get("tags", {}).get("place") not in _PLACE_RANK:
            continue
        hits = tree.query(Point(e["lon"], e["lat"]), predicate="covered_by")
        keys = _place_keys(e["tags"])
        if len(hits) and keys:  # nodes with no Latin-script name cannot match an AGMARKNET name
            places_by_district[dcodes[int(hits[0])]].append(dict(e, _keys=keys))
    district_keys = {match_key(n) for d in districts for n in [d["name_en"], *d["aliases"]["en"]]}
    rows, rep = [], Counter()
    unmapped_districts: set[str] = set()
    for commodity, info in agm["per_commodity"].items():
        for m in info["markets"]:
            if m.get("state_id") != 20 and clean(m.get("state_name")) != AGMARKNET_STATE:
                continue
            meta = mk.get(m["market_id"], {})
            rep["maharashtra_market_commodity_pairs"] += 1
            cat = clean(meta.get("mkt_category"))
            if cat not in APMC_CATEGORIES:
                rep[f"excluded_category:{cat or 'unknown'}"] += 1
                continue
            dname = clean(meta.get("district_name"))
            dc = map_agmarknet_district(dname, districts)
            if dc is None:
                unmapped_districts.add(dname)
            name = clean(m["market_name"])
            if name in MANDI_ADDRESS_PLACES:
                place, dc = MANDI_ADDRESS_PLACES[name]
                geo = geocode_market(place, dc, places_by_district)
                if geo:
                    geo["geocode_source"] += f"; place taken from the AGMARKNET address ({meta.get('mkt_address')})"
            else:
                geo = geocode_market(name, dc, places_by_district, sub_yard=cat == "Sub Market Yard",
                                     district_keys=district_keys) if dc else None
            rows.append({
                "name": name, "agmarknet_name_raw": m["market_name"], "commodity": commodity,
                "agmarknet_market_id": m["market_id"], "agmarknet_commodity_id": info["commodity"]["id"],
                "category": cat, "address": clean(meta.get("mkt_address")) or None, "state": AGMARKNET_STATE,
                "district_name": dname or None, "district_code": dc,
                "lat": geo["lat"] if geo else None, "lon": geo["lon"] if geo else None,
                "geocode_source": geo["geocode_source"] if geo else None,
                "source_url": f"{AGMARKNET_API}list-comm/{info['commodity']['id']}",
            })
    rows.sort(key=lambda r: (r["commodity"], r["name"], r["agmarknet_market_id"]))
    dedup: dict[tuple[str, str], dict] = {}
    for r in rows:  # mandi_markets is UNIQUE (name, commodity): keep the lowest AGMARKNET market id
        if (r["name"], r["commodity"]) in dedup:
            rep["dropped_duplicate_name_commodity"] += 1
            continue
        dedup[(r["name"], r["commodity"])] = r
    rows = list(dedup.values())
    markets = {r["agmarknet_market_id"]: r for r in rows}
    report = dict(rep)
    report.update({
        "rows": len(rows), "unique_markets": len(markets),
        "rows_per_commodity": dict(Counter(r["commodity"] for r in rows)),
        "markets_geocoded": sum(1 for r in markets.values() if r["lat"] is not None),
        "markets_without_district": sorted({r["name"] for r in rows if r["district_code"] is None}),
        "unmapped_agmarknet_districts": sorted(unmapped_districts),
        "markets_not_geocoded": sorted({r["name"] for r in rows if r["lat"] is None}),
    })
    return rows, report


# =====================================================================================================
# KVK contacts (ICAR-ATARI Zone VIII, Pune: "Contact details of KVKs (Zone-VIII, Pune)")
# =====================================================================================================
KVK_DISTRICT_ALIASES: dict[str, str] = {
    "Osmanabad": "dharashiv",
    "Aurangabad": "chhatrapati-sambhajinagar",
    "Ahmednagar": "ahilyanagar",
    "Ahmadnagar": "ahilyanagar",
    "Raigadh": "raigad",
    "Raigarh": "raigad",
    "Gondiya": "gondia",
    "Bid": "beed",
    "Buldana": "buldhana",
    "Jalgoan": "jalgaon",
}
_MOBILE = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")


def fetch_kvk_pdf(*, refresh: bool = False, offline: bool = False) -> Path:
    """The official ATARI Pune KVK telephone directory, via its Internet Archive capture (the official host
    did not resolve in DNS on the retrieval date). The archive serves the original bytes (``id_`` mode)."""
    url = f"https://web.archive.org/web/{ATARI_KVK_PDF_SNAPSHOT}id_/{ATARI_KVK_PDF}"

    def _check(body: bytes) -> None:
        if not body.startswith(b"%PDF"):
            raise ValueError("not a PDF")

    return cached_fetch(url, RAW_DIR / "kvk" / "atari_pune_kvk_telephone_list.pdf", refresh=refresh, offline=offline,
                        validate=_check, timeout=180,
                        note=f"Official URL {ATARI_KVK_PDF}; Internet Archive capture {ATARI_KVK_PDF_SNAPSHOT}")


def _normalise_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    m = re.match(r"\(?(0\d{2,4})\)?", s.strip())
    if not m:
        return digits
    std = m.group(1)
    rest = digits[len(std):]
    return f"{std}-{rest}"


def landline_numbers(text: str) -> list[str]:
    """Indian landline numbers (STD code with leading 0, 11 digits in all) in reading order."""
    out, pos = [], 0
    for m in re.finditer(r"\(?0\d", text):
        if m.start() < pos:
            continue
        k, digits = m.start(), 0
        while k < len(text) and digits < 11 and (text[k].isdigit() or text[k] in " -\u2013()\t"):
            digits += text[k].isdigit()
            k += 1
        if digits == 11 and (k >= len(text) or not text[k].isdigit()):
            out.append(_normalise_phone(text[m.start():k]))
            pos = k
    return out


def parse_kvk_directory(pages: list[str], districts: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    """Parse the Maharashtra section of the directory (pypdf *layout* text, one string per page).

    Columns are located from each page's "Office / Fax / Mobile" header. Only the *office* landline is
    kept; the heads' names and personal mobile numbers are deliberately not extracted.
    """
    by_key = {}
    for d in districts:
        for n in [d["name_en"], *d["aliases"]["en"]]:
            by_key[match_key(n)] = d["code"]
    entries: list[dict] = []
    host, in_mh = None, False
    email_re = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    for page in pages:
        lines = page.splitlines()
        hdr = next((ln for ln in lines if "Office" in ln and "Mobile" in ln), None)
        if hdr is not None:
            office_x, fax_x = hdr.index("Office"), hdr.index("Fax")
        addr_end, fax_start = office_x - 16, (office_x + fax_x) // 2 + 3
        for ln in lines:
            if "State 1" in ln and "Maharashtra" in ln:
                in_mh = True
                continue
            if re.search(r"State\s*2", ln):
                in_mh = False
            if not in_mh:
                continue
            m_host = re.fullmatch(r"\s*((MPKV|VNMKV|PDKV|BSKKV|MAFSU|ICAR|NGO)\b[^0-9]*?)\s*", ln)
            if m_host:
                host = m_host.group(1).strip()
                continue
            sr = re.match(r"^\s{0,8}(\d{1,2})(\s|$)", ln)
            body = ln[:addr_end]
            if sr:
                body = body[:sr.start(1)] + " " * len(sr.group(1)) + body[sr.end(1):]
            text = body.strip()
            email_only = bool(text) and re.fullmatch(email_re + r"[;,]?", text.replace("E-mail", "").strip(" :;"))
            if text and not email_only and (not entries or entries[-1].get("_done")):
                entries.append({"label": text, "host": host, "addr": [], "office": [], "email": None})
            elif not entries:
                continue
            e = entries[-1]
            if sr:
                e["sr"] = int(sr.group(1))
            e["office"].append(ln[addr_end:fax_start] if len(ln) > addr_end else "")
            if text == e["label"] and not e["addr"] and not e.get("_seen_label"):
                e["_seen_label"] = True
            elif re.search(r"E-?\s?mail", text, re.I) or email_only:
                e["email"] = e["email"] or (re.findall(email_re, ln) or [None])[0]
                e["_done"] = True
            elif text and not re.match(r"(Dr|Er|Mr|Mrs|Ms|Shri|Smt)\b\.?\s", text):
                e["addr"].append(re.sub(r"^(Dr|Er|Mr|Mrs|Ms|Shri|Smt)\b\.?[^,]*?(?=Krishi)", "", text))
    out, problems = [], []
    for e in entries:
        joined = ""
        for part in e["office"]:
            part = part.strip()
            if not part:
                continue
            joined += ("" if joined.endswith("-") else " ") + part
        cands, ptype = landline_numbers(joined), "office landline"
        if not cands:  # some KVKs print a 10-digit number in the *Office* column (not the Mobile column)
            cands = [m.group(0) for m in _MOBILE.finditer(joined)]
            ptype = "office (10-digit number printed in the Office column)"
        label = re.sub(r"\s+", " ", e["label"]).strip()
        base = re.sub(r"\s*[-–]\s*(I|II|III|IV)$", "", label).strip()
        dc = KVK_DISTRICT_ALIASES.get(base) or by_key.get(match_key(base))
        rec = {"sr": e.get("sr"), "label": label, "host": e["host"], "district_code": dc,
               "name": f"Krishi Vigyan Kendra, {label}", "address": clean(" ".join(e["addr"])) or None,
               "email": e.get("email"), "phone": cands[0] if cands else None,
               "phone_type": ptype if cands else None}
        if dc is None:
            problems.append(f"#{rec['sr']} {label}: district not recognised")
        if rec["phone"] is None:
            problems.append(f"#{rec['sr']} {label}: no usable number in the Office column")
        out.append(rec)
    return out, {"entries": len(entries), "problems": problems}


# =====================================================================================================
# Geometry outputs
# =====================================================================================================
DB_SIMPLIFY_DEG = 0.0001       # ~11 m: district polygons stored in the database and used for assignment
WEB_SIMPLIFY_STEPS = (0.006, 0.008, 0.01, 0.012, 0.015, 0.02)
WEB_MAX_BYTES = 150 * 1024
WEB_GRID = 1e-4                # coordinate precision of the web file (~11 m)


def simplify_coverage(geoms: list, tolerance: float, grid: float) -> list:
    """Topology-preserving simplification of a polygon coverage (shared edges stay shared; GEOS >= 3.12)."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon

    out = []
    for g in shapely.coverage_simplify(geoms, tolerance):
        g = shapely.set_precision(g, grid)
        if isinstance(g, Polygon):
            g = MultiPolygon([g])
        out.append(g)
    return out


def geometry_json(geom, decimals: int) -> dict:
    from shapely.geometry import mapping

    def rnd(c: Any) -> Any:
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(float(v), decimals) for v in c]
        return [rnd(x) for x in c]

    m = mapping(geom)
    return {"type": m["type"], "coordinates": rnd(m["coordinates"])}


def build_web_geojson(districts: list[dict], geoms: dict[str, Any]) -> tuple[dict, dict]:
    """Simplified district boundaries for the R1 map: smallest tolerance that fits under WEB_MAX_BYTES."""
    import shapely

    codes = [d["code"] for d in districts]
    src = [geoms[c] for c in codes]
    for tol in WEB_SIMPLIFY_STEPS:
        simp = simplify_coverage(src, tol, WEB_GRID)
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"code": d["code"], "name_en": d["name_en"], "name_mr": d["name_mr"],
                                               "name_hi": d["name_hi"]}, "geometry": geometry_json(g, 4)}
            for d, g in zip(districts, simp, strict=True)]}
        size = len(json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode())
        if size <= WEB_MAX_BYTES:
            break
    ratios = {c: round(s.area / o.area, 4) for c, s, o in zip(codes, simp, src, strict=True)}
    info = {"tolerance_deg": tol, "grid_deg": WEB_GRID, "bytes": size, "features": len(fc["features"]),
            "vertices": int(sum(shapely.get_num_coordinates(g) for g in simp)),
            "all_valid": all(g.is_valid and not g.is_empty for g in simp),
            "coverage_valid": bool(shapely.coverage_is_valid(simp)),
            "min_area_ratio": min(ratios.values()), "smallest_district": min(codes, key=lambda c: geoms[c].area)}
    return fc, info


# =====================================================================================================
# Build: raw cache -> data/geo/*.json|csv.gz and apps/web/public/geo/mh-districts.geojson
# =====================================================================================================
@dataclass
class BuildResult:
    districts: list[dict]
    talukas: list[dict]
    villages: list[dict]
    mandis: list[dict]
    kvks: list[dict]
    report: dict


def _meta_dates(*paths: Path) -> list[str]:
    return sorted({read_meta(p).get("retrieved_at", "")[:10] for p in paths if read_meta(p)} - {""})


def build_all(*, refresh: bool = False, offline: bool = False, write: bool = True) -> BuildResult:
    import shapely
    from pypdf import PdfReader

    rep: dict[str, Any] = {"built_at": datetime.now(UTC).isoformat(timespec="seconds")}

    # Districts (Wikidata) and polygons (geoBoundaries ADM2, filtered by the ADM1 Maharashtra polygon).
    districts, excluded = normalise_wikidata_districts(sparql("districts", DISTRICTS_QUERY, refresh=refresh,
                                                              offline=offline))
    if len(districts) != EXPECTED_DISTRICTS:
        raise ValueError(f"expected {EXPECTED_DISTRICTS} districts, got {len(districts)}")
    m1, adm1 = geoboundaries("ADM1", refresh=refresh, offline=offline)
    m2, adm2 = geoboundaries("ADM2", refresh=refresh, offline=offline)
    m3, adm3 = geoboundaries("ADM3", refresh=refresh, offline=offline)
    mh = maharashtra_polygon(adm1)
    adm2_mh = features_in(adm2, mh)
    if len(adm2_mh) != EXPECTED_DISTRICTS:
        raise ValueError(f"geoBoundaries ADM2 has {len(adm2_mh)} Maharashtra features, expected {EXPECTED_DISTRICTS}")
    matched = match_districts_to_adm2(districts, adm2_mh)
    codes = [d["code"] for d in districts]
    db_geoms = dict(zip(codes, simplify_coverage([matched[c]["geometry"] for c in codes], DB_SIMPLIFY_DEG, 1e-6),
                        strict=True))
    feats = {c: {"geometry": db_geoms[c], "properties": matched[c]["properties"]} for c in codes}
    for d in districts:
        f = matched[d["code"]]
        lon, lat = inner_centroid(db_geoms[d["code"]])
        d.update({
            "lon": lon, "lat": lat, "centroid_source": "geoboundaries:ADM2 polygon centroid",
            "boundary_source": "geoBoundaries gbOpen IND ADM2", "boundary_source_url": m2["gjDownloadURL"],
            "boundary_licence": m2["boundaryLicense"], "gb_shape_name": f["properties"]["shapeName"],
            "gb_shape_id": f["properties"]["shapeID"], "gb_overlap_with_adm1": f["properties"]["overlap"],
        })
        if d["gb_shape_name"] != d["name_en"] and d["gb_shape_name"] not in d["aliases"]["en"]:
            d["aliases"]["en"] = sorted(d["aliases"]["en"] + [d["gb_shape_name"]])
        d["boundary"] = geometry_json(db_geoms[d["code"]], 6)
    rep["districts"] = {
        "count": len(districts), "excluded_wikidata_items": excluded,
        "geoboundaries_adm2_features_in_maharashtra": len(adm2_mh),
        "renames_via_alias_table": {k: next(d["code"] for d in districts if d["qid"] == v)
                                    for k, v in GB_ADM2_ALIASES.items()},
        "name_hi_sources": dict(Counter(d["name_sources"]["hi"].split(" ")[0] for d in districts)),
        "db_simplify_tolerance_deg": DB_SIMPLIFY_DEG,
        "db_boundary_vertices": int(sum(shapely.get_num_coordinates(g) for g in db_geoms.values())),
    }

    # OSM settlements (villages + geocoding), talukas.
    osm = fetch_osm_places(mh, refresh=refresh, offline=offline)
    osm_admin = fetch_osm_admin_names(mh, refresh=refresh, offline=offline)
    talukas_wd, tex = normalise_wikidata_talukas(sparql("talukas", TALUKAS_QUERY, refresh=refresh, offline=offline),
                                                 districts, osm_admin)
    adm3_mh = features_in(adm3, mh)
    merged = {dc for dc, _ in GB_ADM3_MERGED}
    wd_hq = wikidata_settlements([t["name_en"] for t in talukas_wd if t["district_code"] in merged
                                  and not t["wikidata_coords"]], refresh=refresh, offline=offline)
    talukas, tpolys, trep = build_talukas(talukas_wd, districts, feats, adm3_mh, osm, wd_hq)
    trep["wikidata_talukas"] = len(talukas_wd)
    trep["excluded_wikidata_items"] = tex
    trep["name_sources"] = {lang: dict(Counter(t["name_sources"][lang].split(" ")[0] for t in talukas))
                            for lang in ("en", "mr", "hi")}
    rep["talukas"] = trep

    wd_village = wikidata_labels([e.get("tags", {}).get("wikidata", "") for e in osm
                                  if e.get("tags", {}).get("place") in PLACE_TYPES_VILLAGE],
                                 refresh=refresh, offline=offline)
    villages, vrep = build_villages(osm, feats, talukas, tpolys, wd_village)
    vrep["osm_snapshot"] = osm_snapshot_dates()
    vrep["districts_without_villages"] = sorted(set(codes) - set(vrep["per_district"]))
    rep["villages"] = vrep

    # Mandis.
    agm = fetch_agmarknet(refresh=refresh, offline=offline)
    mandis, mrep = build_mandis(agm, districts, feats, osm)
    rep["mandis"] = mrep

    # KVKs.
    pdf = fetch_kvk_pdf(refresh=refresh, offline=offline)
    pages = [p.extract_text(extraction_mode="layout") for p in PdfReader(pdf).pages]
    kvk_all, krep = parse_kvk_directory(pages, districts)
    verified = datetime.strptime(ATARI_KVK_PDF_SNAPSHOT[:8], "%Y%m%d").date().isoformat()
    kvks = []
    for k in kvk_all:
        if k["district_code"] and k["phone"]:
            kvks.append({**k, "source_url": ATARI_KVK_PDF,
                         "archive_url": f"https://web.archive.org/web/{ATARI_KVK_PDF_SNAPSHOT}/{ATARI_KVK_PDF}",
                         "verified_at": verified})
    krep.update({"kvks_in_directory": len(kvk_all), "kvks_kept": len(kvks),
                 "districts_covered": sorted({k["district_code"] for k in kvks}),
                 "districts_without_kvk_contact": sorted(set(codes) - {k["district_code"] for k in kvks})})
    rep["kvk"] = krep

    web, wrep = build_web_geojson(districts, db_geoms)
    rep["web_geojson"] = wrep
    rep["retrieved"] = {
        "wikidata": _meta_dates(RAW_DIR / "wikidata" / "districts.json", RAW_DIR / "wikidata" / "talukas.json"),
        "geoboundaries": _meta_dates(*(RAW_DIR / "geoboundaries" / f"IND_{lvl}.geojson" for lvl in ("ADM1", "ADM2",
                                                                                                    "ADM3"))),
        "osm": _meta_dates(*sorted((RAW_DIR / "osm").glob("places_*.json"))),
        "agmarknet": _meta_dates(*sorted((RAW_DIR / "agmarknet").glob("*.json"))),
        "kvk_pdf": _meta_dates(pdf),
    }
    rep["geoboundaries_meta"] = {lvl: {k: m.get(k) for k in ("boundaryID", "boundaryYearRepresented", "boundarySource",
                                                               "boundaryLicense", "licenseSource", "gjDownloadURL",
                                                               "buildDate")}
                                 for lvl, m in (("ADM1", m1), ("ADM2", m2), ("ADM3", m3))}
    result = BuildResult(districts, talukas, villages, mandis, kvks, rep)
    if write:
        write_outputs(result, web)
    return result


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def write_outputs(res: BuildResult, web: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # One compact line per district (the boundary geometry would otherwise take a line per coordinate).
    head = json.dumps({"source": "Wikidata (CC0) + geoBoundaries ADM2 (ODbL 1.0)", "count": len(res.districts)},
                      ensure_ascii=False)[:-1]
    body = ",\n".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in res.districts)
    (OUT_DIR / "districts.json").write_text(f'{head}, "districts": [\n{body}\n]}}\n', encoding="utf-8")
    _dump(OUT_DIR / "talukas.json", {"source": "Wikidata (CC0) + geoBoundaries ADM3 (ODbL 1.0) + OSM (ODbL 1.0)",
                                     "count": len(res.talukas), "talukas": res.talukas})
    write_villages_csv(res.villages, OUT_DIR / "villages.csv.gz")
    _dump(OUT_DIR / "mandis.json", {"source": "AGMARKNET 2.0 public API; geocodes from OpenStreetMap (ODbL 1.0)",
                                    "count": len(res.mandis), "mandis": res.mandis})
    _dump(OUT_DIR / "kvk.json", {"source": "ICAR-ATARI Zone VIII, Pune: Contact details of KVKs (official PDF)",
                                 "note": "Office numbers only; KVK heads' names and personal mobiles are not stored.",
                                 "count": len(res.kvks), "kvks": res.kvks})
    (OUT_DIR / "SOURCE.md").write_text(source_md(res), encoding="utf-8")
    WEB_GEO_DIR.mkdir(parents=True, exist_ok=True)
    (WEB_GEO_DIR / "mh-districts.geojson").write_text(json.dumps(web, ensure_ascii=False, separators=(",", ":")),
                                                      encoding="utf-8")
    (WEB_GEO_DIR / "SOURCE.md").write_text(web_source_md(res), encoding="utf-8")


def load_outputs() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    return (load_json(OUT_DIR / "districts.json")["districts"], load_json(OUT_DIR / "talukas.json")["talukas"],
            read_villages_csv(OUT_DIR / "villages.csv.gz"), load_json(OUT_DIR / "mandis.json")["mandis"],
            load_json(OUT_DIR / "kvk.json")["kvks"])


def outputs_exist() -> bool:
    return all((OUT_DIR / n).exists() for n in ("districts.json", "talukas.json", "villages.csv.gz", "mandis.json",
                                                "kvk.json"))


# =====================================================================================================
# SOURCE.md
# =====================================================================================================
def _pct(n: int, d: int) -> str:
    return f"{n} ({100 * n / d:.1f}%)" if d else str(n)


def source_md(res: BuildResult) -> str:
    r = res.report
    v, t, m, k, w = r["villages"], r["talukas"], r["mandis"], r["kvk"], r["web_geojson"]
    gb = r["geoboundaries_meta"]
    nv, nt = len(res.villages), len(res.talukas)
    vs = v["name_sources"]
    mr_dev = sum(n for s, n in vs["mr"].items() if s != "latin_fallback")
    hi_own = sum(n for s, n in vs["hi"].items() if s not in ("mr_fallback", "latin_fallback"))
    t_mr_dev = sum(1 for x in res.talukas if is_devanagari(x["name_mr"]))
    t_hi_own = sum(1 for x in res.talukas if x["name_sources"]["hi"].startswith("wikidata"))
    nc = v["nearest_centroid_vs_polygon"]
    lines = [
        "# Maharashtra geographic reference data: sources and methods",
        "",
        f"Generated by `apps/api/app/services/foundry/geo_sources.py` (`build_all`) on {r['built_at'][:10]}. "
        "Seeded into Postgres by `apps/api/scripts/seed_locations.py`. Raw downloads are cached (not committed) "
        "under `apps/api/data/raw_external/geo/`, each with a `.meta.json` sidecar (URL, retrieval time, SHA-256).",
        "",
        "## Licences and attribution",
        "",
        "| Data | Source | Licence | Retrieved |",
        "|---|---|---|---|",
        f"| District and taluka names, LGD codes | Wikidata, {WIKIDATA_SPARQL} | CC0 1.0 | "
        f"{', '.join(r['retrieved']['wikidata'])} |",
        f"| District polygons | geoBoundaries gbOpen IND ADM2 ({gb['ADM2']['boundaryID']}, {gb['ADM2']['boundaryYearRepresented']}; "
        f"source {gb['ADM2']['boundarySource']}), {gb['ADM2']['gjDownloadURL']} | {gb['ADM2']['boundaryLicense']} | "
        f"{', '.join(r['retrieved']['geoboundaries'])} |",
        f"| Sub-district polygons (taluka assignment only) | geoBoundaries gbOpen IND ADM3 ({gb['ADM3']['boundaryID']}, "
        f"{gb['ADM3']['boundaryYearRepresented']}) | {gb['ADM3']['boundaryLicense']} | same |",
        f"| Maharashtra outline (spatial filter only) | geoBoundaries gbOpen IND ADM1 ({gb['ADM1']['boundarySource']}) | "
        f"{gb['ADM1']['boundaryLicense']} | same |",
        f"| Villages, hamlets, towns; settlement geocodes | OpenStreetMap via Overpass API | ODbL 1.0, "
        f"© OpenStreetMap contributors | {', '.join(r['retrieved']['osm'])} (OSM base "
        f"{', '.join(sorted({s[:10] for s in v['osm_snapshot']}))}) |",
        f"| Mandi markets | AGMARKNET 2.0 public API, {AGMARKNET_API} (`dashboard-market-filter`, `commodities`, "
        f"`list-comm/{{commodity_id}}`) | Government of India open data | {', '.join(r['retrieved']['agmarknet'])} |",
        f"| KVK office telephone numbers | ICAR-ATARI Zone VIII, Pune, \"Contact details of KVKs (Zone-VIII, Pune)\", "
        f"{ATARI_KVK_PDF} (Internet Archive capture {ATARI_KVK_PDF_SNAPSHOT}) | official publication | "
        f"{', '.join(r['retrieved']['kvk_pdf'])} |",
        "",
        "Files derived from ODbL sources (`villages.csv.gz`, district boundaries in `districts.json`, "
        "`talukas.json` centroids, mandi geocodes, `apps/web/public/geo/mh-districts.geojson`) are made available "
        "under the ODbL 1.0; attribute \"© OpenStreetMap contributors\" and \"geoBoundaries\".",
        "",
        "## Counts",
        "",
        f"* Districts: **{len(res.districts)}** (Wikidata items that are districts of India in Maharashtra *and* "
        f"carry an LGD district code; excluded: "
        f"{', '.join(x['qid'] + ' ' + str(x['label']) + ' (' + x['reason'] + ')' for x in r['districts']['excluded_wikidata_items']) or 'none'}).",
        f"* Talukas: **{nt}**: {t['wikidata_talukas']} Wikidata talukas of Maharashtra plus "
        f"{len(t['district_equivalent_units'])} district-equivalent unit ({', '.join(t['district_equivalent_units'])}; "
        "Wikidata lists no taluka for Mumbai City, while LGD/geoBoundaries ADM3 has one sub-district covering it), "
        f"minus {len(t['dropped'])} dropped ({'; '.join(t['dropped']) or 'none'}).",
        f"* Villages: **{nv}** OSM nodes ({', '.join(f'{p}: {n}' for p, n in sorted(v['by_place'].items()))}); "
        f"dropped: no name {v.get('dropped_no_name', 0)}, outside Maharashtra {v.get('dropped_outside_maharashtra', 0)}, "
        f"duplicates {v.get('dropped_duplicate', 0)}, in a district without talukas "
        f"{v.get('dropped_district_without_taluka', 0)}. Districts without villages: "
        f"{', '.join(v['districts_without_villages']) or 'none'}.",
        f"* Mandi rows (market x commodity): **{m['rows']}** covering **{m['unique_markets']}** APMC markets "
        f"({', '.join(f'{c}: {n}' for c, n in m['rows_per_commodity'].items())}); markets with coordinates: "
        f"**{m['markets_geocoded']}**/{m['unique_markets']}.",
        f"* KVK contacts: **{k['kvks_kept']}** of {k['kvks_in_directory']} Maharashtra KVKs (office numbers only), "
        f"covering {len(k['districts_covered'])}/{len(res.districts)} districts. No contact for: "
        f"{', '.join(k['districts_without_kvk_contact']) or 'none'} (the app falls back to the Kisan Call Centre).",
        "",
        "## Methods",
        "",
        "### Districts",
        "",
        "* `code` is a slug of the current official English name (`chhatrapati-sambhajinagar`, `dharashiv`, "
        "`ahilyanagar`, ...). It is the join key for `districts.code`, the web GeoJSON `code` property and the API.",
        "* Names: English = Wikidata English label without \"district\"; Marathi = the Marathi Wikipedia sitelink "
        "title (falls back to the Marathi label) without \"जिल्हा\"; Hindi = the Hindi label without \"जिला\". "
        "For renamed districts an explicit table (`DISTRICT_CURRENT_NAMES`) selects the current name among the "
        "item's own Wikidata strings; the build fails if the string is not on the item. Former names are kept "
        "in `aliases`.",
        "* Chhatrapati Sambhajinagar: no Wikidata Hindi string carries the full current name (the Hindi label "
        "is \"संभाजीनगर जिला\"), so `name_hi` uses the current Devanagari Marathi name and is flagged "
        "`mr_fallback`.",
        f"* Polygons: geoBoundaries ADM2 features whose area lies at least 50% inside the ADM1 Maharashtra "
        f"polygon: {r['districts']['geoboundaries_adm2_features_in_maharashtra']} features (Palghar is present). "
        f"Matched 1:1 to Wikidata by name; explicit alias table for "
        f"{', '.join(f'{a} -> {c}' for a, c in r['districts']['renames_via_alias_table'].items())}.",
        f"* Stored boundary: topology-preserving coverage simplification (GEOS `coverage_simplify`) at "
        f"{DB_SIMPLIFY_DEG} deg (~11 m), {r['districts']['db_boundary_vertices']} vertices. The centroid is the "
        "polygon centroid (or a point on the surface if the centroid falls outside). Wikidata coordinates are "
        "kept in `wikidata_coords` but not used: some are wrong (Solapur and Dharashiv share one).",
        "",
        "### Talukas",
        "",
        "* Wikidata items of class \"taluka of Maharashtra\" (Q13119795) located in an official district; all "
        "carry an LGD sub-district code. Names: English label without \"taluka\"; Marathi = Marathi Wikipedia "
        "title, else label; Hindi = Hindi label, else Hindi Wikipedia title, else the Marathi Devanagari name "
        "(`mr_fallback`); OSM boundary relations linked by `wikidata=*` fill Marathi/Hindi gaps. Renamed talukas "
        "(`TALUKA_CURRENT_NAMES`: Chhatrapati Sambhajinagar, Dharashiv) take the current name from the item's own "
        "English alias; the former name stays in `aliases`.",
        f"* Marathi in Devanagari: {_pct(t_mr_dev, nt)}; Hindi from a Wikidata Hindi string: {_pct(t_hi_own, nt)}; "
        f"name sources: {json.dumps(t['name_sources'], ensure_ascii=False)}.",
        f"* Polygons and centroids: geoBoundaries ADM3 (2018) units matched by name within the district "
        f"({t['with_adm3_polygon']} talukas; {len(t['adm3_alias_matches'])} via the reviewed spelling table "
        f"`GB_ADM3_ALIASES`; merged unit: {', '.join(t['merged_units'])}). Centroid sources: "
        f"{json.dumps(t['centroid_sources'])}.",
        "",
        "### Villages",
        "",
        "* OSM nodes tagged `place=village|hamlet|town` with a name, fetched in 1-degree tiles over the "
        "Maharashtra bounding box and kept only inside a district polygon (nodes up to 1 km offshore go to the "
        "nearest district).",
        "* District = the polygon that covers the node. Taluka = the geoBoundaries ADM3 polygon of a taluka of "
        "that district that covers the node; otherwise (Mumbai Suburban's three talukas share one ADM3 unit, "
        "or ADM2/ADM3 edge slivers) the nearest taluka centroid within the district. `taluka_method` records "
        f"which: {json.dumps(v['taluka_method'])}.",
        f"* Error of the nearest-centroid rule: compared with polygon containment on {nc['compared']} villages, "
        f"nearest-centroid picks a different taluka for {nc['compared'] - nc['agree']} "
        f"(**{100 * (nc['disagreement_rate'] or 0):.1f}%**). That is why polygon containment is the primary "
        "method; `nearest_centroid_taluka_code` is kept in the CSV for comparison.",
        "* Names (never machine-transliterated): `name_en` = `name:en`, else `name` if Latin, else `name` as is. "
        "`name_mr` = `name:mr`, else the Wikidata Marathi label of the node's `wikidata` item, else `name` if "
        "Devanagari, else the Latin name (flag `latin_fallback`). `name_hi` = `name:hi`, else the Wikidata Hindi "
        "label, else the Devanagari Marathi name (flag `mr_fallback`), else the Latin name (`latin_fallback`).",
        f"* Coverage: Marathi in Devanagari {_pct(mr_dev, nv)}; Marathi copied from the Latin name "
        f"{_pct(vs['mr'].get('latin_fallback', 0), nv)}; Hindi from a Hindi source {_pct(hi_own, nv)}; Hindi from "
        f"the Marathi name {_pct(vs['hi'].get('mr_fallback', 0), nv)}; Hindi copied from the Latin name "
        f"{_pct(vs['hi'].get('latin_fallback', 0), nv)}. Full breakdown: "
        f"`{json.dumps(vs, ensure_ascii=False)}`.",
        "* Natural key used by the seed: (name_en, lat, lon). OSM ids are in the CSV (`osm_id`).",
        "",
        "### Mandi markets",
        "",
        "* Markets that AGMARKNET lists for each of the six crops' AGMARKNET commodities "
        f"({', '.join(app_commodities())}, from `packages/shared/crops.json`) via `list-comm/{{commodity_id}}`, "
        f"in Maharashtra, of category {' or '.join(APMC_CATEGORIES)} (APMC yards). Excluded: "
        f"{json.dumps({k2: v2 for k2, v2 in m.items() if k2.startswith('excluded_category')})}.",
        "* `name` is AGMARKNET's spelling with surrounding whitespace removed (`agmarknet_name_raw` keeps the exact "
        "string). `district_name` is AGMARKNET's district; `district_code` maps it with the reviewed table "
        "`AGMARKNET_DISTRICT_ALIASES`.",
        "* AGMARKNET's per-market price, profile and GIS endpoints require a CAPTCHA and were not used. "
        "data.gov.in needs an API key (none configured).",
        "* Geocoding (settlement-level, never guessed): the OSM place node inside the market's district whose "
        "name equals the place the market is named after (for a Sub Market Yard the bracketed place first, e.g. "
        "Dhad for `Buldhana(Dhad)`; a bracketed district name such as `APMC Ashti(Jalna)` is ignored), after the "
        "reviewed spelling table `MANDI_PLACE_ALIASES` (AGMARKNET spelling -> official town spelling) and the "
        "address table `MANDI_ADDRESS_PLACES` (the Mumbai APMC yards are at Vashi, Navi Mumbai, Thane district, "
        "per AGMARKNET's own address); a fuzzy match (ratio >= 0.88, unique) is allowed only against towns and "
        "cities. "
        "Ambiguous or unmatched markets keep `lat`/`lon` null. `geocode_source` names the OSM node. "
        "The point is the settlement, not the market yard, and can be a few kilometres from the yard.",
        f"* Not geocoded ({len(m['markets_not_geocoded'])}): {', '.join(m['markets_not_geocoded'])}.",
        "",
        "### KVK contacts",
        "",
        "* Parsed from the layout text of the official PDF (created 2023-04-13). Only numbers in the *Office* "
        "column are used (landline first; a 10-digit number printed in the Office column is accepted and "
        "flagged in `phone_type`). The heads' names and their personal mobile numbers are not stored.",
        f"* `verified_at` = {ATARI_KVK_PDF_SNAPSHOT[:4]}-{ATARI_KVK_PDF_SNAPSHOT[4:6]}-{ATARI_KVK_PDF_SNAPSHOT[6:8]}, "
        "the date the Internet Archive captured the official file; `ataripune.icar.gov.in` did not resolve in "
        "DNS on the retrieval date, so the numbers were not re-checked against a live official page. "
        f"Parser notes: {'; '.join(k['problems']) or 'none'}.",
        "",
        "### Web map file",
        "",
        f"`apps/web/public/geo/mh-districts.geojson`: {w['features']} features, {w['bytes']} bytes, coverage "
        f"simplification at {w['tolerance_deg']} deg, coordinates on a {w['grid_deg']} deg grid, {w['vertices']} "
        f"vertices, all valid: {w['all_valid']}, coverage valid: {w['coverage_valid']}, smallest area ratio after "
        f"simplification {w['min_area_ratio']} (smallest district: {w['smallest_district']}).",
        "",
    ]
    return "\n".join(lines)


def web_source_md(res: BuildResult) -> str:
    w = res.report["web_geojson"]
    gb = res.report["geoboundaries_meta"]["ADM2"]
    return "\n".join([
        "# mh-districts.geojson",
        "",
        "Maharashtra district boundaries for the R1 risk map (Maharashtra only; no national boundary is drawn).",
        "",
        "* **Attribution (show in the R1 footer):** District boundaries: geoBoundaries "
        "(https://www.geoboundaries.org), source Pathways Data Pvt. Ltd. / lgdirectory.gov.in. "
        "Names: Wikidata.",
        f"* **Source:** geoBoundaries gbOpen IND ADM2, {gb['boundaryID']} ({gb['boundaryYearRepresented']}), "
        f"{gb['gjDownloadURL']}, retrieved {', '.join(res.report['retrieved']['geoboundaries'])}.",
        f"* **Licence:** {gb['boundaryLicense']} (share-alike: this modified file is published under the ODbL 1.0). "
        "District names from Wikidata (CC0).",
        f"* **Processing:** Maharashtra districts selected by >= 50% overlap with the ADM1 Maharashtra polygon; "
        f"topology-preserving coverage simplification (GEOS coverage_simplify, shared borders stay shared) at "
        f"{w['tolerance_deg']} degrees; coordinates snapped to {w['grid_deg']} degrees. {w['features']} features, "
        f"{w['bytes']} bytes, {w['vertices']} vertices; smallest district ({w['smallest_district']}) keeps "
        f"{100 * w['min_area_ratio']:.1f}% of its area.",
        "* **Properties:** `code` (same slug as `districts.code` in the database), `name_en`, `name_mr`, `name_hi`.",
        "* Regenerate with `uv run python scripts/seed_locations.py --rebuild` from `apps/api`.",
        "",
    ])
