"""Maharashtra location seed (scripts/seed_locations.py) against the PostGIS test database.

Seeds once per module from the committed files in apps/api/data/geo (no network), then checks the
contract the onboarding picker and the R1 map rely on.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import API_ROOT, REPO_ROOT
from app.core.db import SessionLocal, get_engine
from app.services.foundry import geo_sources as gs

pytestmark = pytest.mark.db

sys.path.insert(0, str(API_ROOT / "scripts"))
import seed_locations  # noqa: E402

GEOJSON = REPO_ROOT / "apps" / "web" / "public" / "geo" / "mh-districts.geojson"
DEVANAGARI_ONLY = re.compile(r"^[ऀ-ॿ\s.()\-]+$")
GEO_TABLES = "kvk_contacts, mandi_markets, villages, talukas, district_boundaries, districts"


@pytest.fixture(autouse=True)
def clean_db():
    """Override the conftest per-test wipe: this module seeds once and only reads afterwards."""
    yield


@pytest.fixture(scope="module")
def seeded() -> dict:
    if not gs.outputs_exist():
        pytest.skip("apps/api/data/geo is missing; run scripts/seed_locations.py --rebuild")
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {GEO_TABLES} RESTART IDENTITY CASCADE"))
    data = gs.load_outputs()
    s = SessionLocal()
    try:
        first = seed_locations.seed(s, data)
        s.commit()
        second = seed_locations.seed(s, data)
        s.commit()
        counts = seed_locations.table_counts(s)
    finally:
        s.close()
    yield {"first": first, "second": second, "counts": counts, "data": data}
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {GEO_TABLES} RESTART IDENTITY CASCADE"))


def q(sql: str, **params):
    with get_engine().connect() as c:
        return c.execute(text(sql), params).all()


def test_36_districts(seeded):
    assert seeded["counts"]["districts"] == 36
    codes = {r.code for r in q("SELECT code FROM districts")}
    for current in ("chhatrapati-sambhajinagar", "dharashiv", "ahilyanagar", "palghar", "mumbai-city"):
        assert current in codes
    assert not codes & {"aurangabad", "osmanabad", "ahmednagar"}


def test_every_district_has_boundary_and_devanagari_marathi_name(seeded):
    rows = q("""SELECT d.code, d.name_mr, d.name_hi, b.district_id IS NOT NULL AS has_b,
                       ST_IsValid(b.geom) AS valid, GeometryType(b.geom) AS gtype,
                       ST_Covers(b.geom, d.centroid::geometry) AS centroid_inside, b.licence, b.source_url
                FROM districts d LEFT JOIN district_boundaries b ON b.district_id = d.id""")
    assert len(rows) == 36
    for r in rows:
        assert r.has_b and r.valid and r.gtype == "MULTIPOLYGON", r.code
        assert r.centroid_inside, r.code
        assert DEVANAGARI_ONLY.match(r.name_mr), (r.code, r.name_mr)
        assert DEVANAGARI_ONLY.match(r.name_hi), (r.code, r.name_hi)
        assert "Open Database License" in r.licence and r.source_url.startswith("https://")
    # Boundaries tile the state: no two districts overlap by more than a sliver.
    overlap = q("""SELECT max(ST_Area(ST_Intersection(a.geom, b.geom))) AS m FROM district_boundaries a
                   JOIN district_boundaries b ON a.district_id < b.district_id AND ST_Intersects(a.geom, b.geom)""")
    assert (overlap[0].m or 0) < 1e-6


def test_every_taluka_belongs_to_a_district(seeded):
    assert seeded["counts"]["talukas"] >= 358
    orphans = q("SELECT count(*) AS n FROM talukas t LEFT JOIN districts d ON d.id = t.district_id WHERE d.id IS NULL")
    assert orphans[0].n == 0
    empty = q("""SELECT d.code FROM districts d WHERE NOT EXISTS (SELECT 1 FROM talukas t WHERE t.district_id = d.id)""")
    assert empty == []
    outside = q("""SELECT t.code FROM talukas t JOIN district_boundaries b ON b.district_id = t.district_id
                   WHERE NOT ST_DWithin(b.geom::geography, t.centroid, 2000)""")
    assert outside == [], outside


def test_villages_exist_for_every_district(seeded):
    assert seeded["counts"]["villages"] > 10000
    rows = q("""SELECT d.code, count(v.id) AS n FROM districts d JOIN talukas t ON t.district_id = d.id
                LEFT JOIN villages v ON v.taluka_id = t.id GROUP BY d.code""")
    missing = [r.code for r in rows if r.n == 0]
    assert missing == [], f"districts without villages: {missing}"
    far = q("""SELECT count(*) AS n FROM villages v JOIN talukas t ON t.id = v.taluka_id
               JOIN district_boundaries b ON b.district_id = t.district_id
               WHERE NOT ST_DWithin(b.geom::geography, ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)::geography, 1100)""")
    assert far[0].n == 0
    blank = q("SELECT count(*) AS n FROM villages WHERE name_en = '' OR name_mr = '' OR name_hi = ''")
    assert blank[0].n == 0


def test_geojson_codes_match_districts_table(seeded):
    fc = json.loads(GEOJSON.read_text(encoding="utf-8"))
    assert GEOJSON.stat().st_size < 150 * 1024
    feats = fc["features"]
    db = {r.code: r for r in q("SELECT code, name_en, name_mr, name_hi FROM districts")}
    assert sorted(f["properties"]["code"] for f in feats) == sorted(db)
    for f in feats:
        p = f["properties"]
        assert set(p) == {"code", "name_en", "name_mr", "name_hi"}
        r = db[p["code"]]
        assert (p["name_en"], p["name_mr"], p["name_hi"]) == (r.name_en, r.name_mr, r.name_hi)
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon") and f["geometry"]["coordinates"]
    assert (GEOJSON.parent / "SOURCE.md").exists()


def test_second_seed_changes_nothing(seeded):
    changed = {t: s for t, s in seeded["second"].items() if s["inserted"] or s["updated"] or s["deleted"]}
    assert changed == {}
    assert seeded["first"]["villages"]["inserted"] == seeded["counts"]["villages"]


def test_mandis_and_kvks_carry_provenance(seeded):
    commodities = set(gs.app_commodities())
    rows = q("SELECT name, commodity, state, district_id, lat, lon, geocode_source FROM mandi_markets")
    assert rows and all(r.commodity in commodities and r.state == "Maharashtra" for r in rows)
    assert all(r.district_id is not None for r in rows)
    assert all((r.lat is None) == (r.geocode_source is None) for r in rows)
    geocoded = q("""SELECT count(*) AS n FROM mandi_markets m JOIN district_boundaries b ON b.district_id = m.district_id
                    WHERE m.lat IS NOT NULL AND NOT ST_Covers(b.geom, ST_SetSRID(ST_MakePoint(m.lon, m.lat), 4326))""")
    assert geocoded[0].n == 0
    kvk = q("SELECT phone, source_url, verified_at, district_id FROM kvk_contacts")
    assert kvk and all(r.district_id and r.source_url.startswith("https://") and r.verified_at for r in kvk)
    assert all(re.fullmatch(r"0\d{2,4}-\d{6,8}|[6-9]\d{9}", r.phone) for r in kvk)


def test_seed_reads_committed_files_only():
    """The committed outputs are self-contained (no raw cache needed to seed)."""
    assert gs.outputs_exist()
    districts = json.loads((Path(gs.OUT_DIR) / "districts.json").read_text(encoding="utf-8"))["districts"]
    assert all(d["boundary"]["type"] == "MultiPolygon" for d in districts)
