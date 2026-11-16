"""PRD §10.1 seed_locations: Maharashtra districts, district boundaries, talukas, villages, APMC mandi
markets and KVK contacts, from the normalised files in apps/api/data/geo (see SOURCE.md there).

Idempotent: districts upsert by `code`, talukas by `code`, villages by the natural key
(name_en, lat, lon) from OpenStreetMap, boundaries by district, mandis by (name, commodity), KVKs by (district, name).
Rows are only written when a value differs, so a second run reports zero changes.

    uv run python scripts/seed_locations.py              # seed from data/geo (builds it first if missing)
    uv run python scripts/seed_locations.py --rebuild    # rebuild data/geo from the raw cache, then seed
    uv run python scripts/seed_locations.py --rebuild --offline   # same, never touching the network
    uv run python scripts/seed_locations.py --refresh    # re-download every source, rebuild, seed
    uv run python scripts/seed_locations.py --prune      # also delete villages/talukas/KVKs no longer in the files

After the first build the seed needs no network: it reads data/geo, and --rebuild reads the raw cache in
data/raw_external/geo.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.services.foundry import geo_sources as gs

DISTRICT_UPSERT = text("""
INSERT INTO districts (code, name_en, name_mr, name_hi, centroid, source_url)
VALUES (:code, :name_en, :name_mr, :name_hi, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :source_url)
ON CONFLICT (code) DO UPDATE SET name_en = EXCLUDED.name_en, name_mr = EXCLUDED.name_mr, name_hi = EXCLUDED.name_hi,
  centroid = EXCLUDED.centroid, source_url = EXCLUDED.source_url
WHERE (districts.name_en, districts.name_mr, districts.name_hi, districts.source_url,
       ST_AsBinary(districts.centroid::geometry))
  IS DISTINCT FROM (EXCLUDED.name_en, EXCLUDED.name_mr, EXCLUDED.name_hi, EXCLUDED.source_url,
       ST_AsBinary(EXCLUDED.centroid::geometry))
RETURNING (xmax = 0) AS inserted
""")

BOUNDARY_UPSERT = text("""
INSERT INTO district_boundaries (district_id, geom, source, source_url, licence)
SELECT d.id, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)), :source, :source_url, :licence
FROM districts d WHERE d.code = :code
ON CONFLICT (district_id) DO UPDATE SET geom = EXCLUDED.geom, source = EXCLUDED.source,
  source_url = EXCLUDED.source_url, licence = EXCLUDED.licence
WHERE (ST_AsBinary(district_boundaries.geom), district_boundaries.source, district_boundaries.source_url,
       district_boundaries.licence)
  IS DISTINCT FROM (ST_AsBinary(EXCLUDED.geom), EXCLUDED.source, EXCLUDED.source_url, EXCLUDED.licence)
RETURNING (xmax = 0) AS inserted
""")

TALUKA_UPSERT = text("""
INSERT INTO talukas (district_id, code, name_en, name_mr, name_hi, centroid)
SELECT d.id, :code, :name_en, :name_mr, :name_hi, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
FROM districts d WHERE d.code = :district_code
ON CONFLICT (code) DO UPDATE SET district_id = EXCLUDED.district_id, name_en = EXCLUDED.name_en,
  name_mr = EXCLUDED.name_mr, name_hi = EXCLUDED.name_hi, centroid = EXCLUDED.centroid
WHERE (talukas.district_id, talukas.name_en, talukas.name_mr, talukas.name_hi, ST_AsBinary(talukas.centroid::geometry))
  IS DISTINCT FROM (EXCLUDED.district_id, EXCLUDED.name_en, EXCLUDED.name_mr, EXCLUDED.name_hi,
       ST_AsBinary(EXCLUDED.centroid::geometry))
RETURNING (xmax = 0) AS inserted
""")

MANDI_UPSERT = text("""
INSERT INTO mandi_markets (name, commodity, district_id, lat, lon, state, district_name, geocode_source)
VALUES (:name, :commodity, (SELECT id FROM districts WHERE code = :district_code), :lat, :lon, :state,
        :district_name, :geocode_source)
ON CONFLICT (name, commodity) DO UPDATE SET district_id = EXCLUDED.district_id, lat = EXCLUDED.lat,
  lon = EXCLUDED.lon, state = EXCLUDED.state, district_name = EXCLUDED.district_name,
  geocode_source = EXCLUDED.geocode_source
WHERE (mandi_markets.district_id, mandi_markets.lat, mandi_markets.lon, mandi_markets.state,
       mandi_markets.district_name, mandi_markets.geocode_source)
  IS DISTINCT FROM (EXCLUDED.district_id, EXCLUDED.lat, EXCLUDED.lon, EXCLUDED.state, EXCLUDED.district_name,
       EXCLUDED.geocode_source)
RETURNING (xmax = 0) AS inserted
""")

VILLAGE_KEY = "v.name_en = t.name_en AND v.lat = t.lat AND v.lon = t.lon"  # natural key: OSM name + position


def _count(result) -> tuple[int, int]:
    rows = result.fetchall()
    ins = sum(1 for r in rows if r.inserted)
    return ins, len(rows) - ins


def _add(stats: dict, table: str, ins: int = 0, upd: int = 0, dele: int = 0) -> None:
    s = stats.setdefault(table, {"inserted": 0, "updated": 0, "deleted": 0})
    s["inserted"] += ins
    s["updated"] += upd
    s["deleted"] += dele


def seed(db: Session, data: tuple | None = None, *, prune: bool = False) -> dict[str, Any]:
    """Upsert everything into the session's database. Returns per-table inserted/updated/deleted counts."""
    districts, talukas, villages, mandis, kvks = data or gs.load_outputs()
    stats: dict[str, Any] = {}

    for d in districts:
        ins, upd = _count(db.execute(DISTRICT_UPSERT, {k: d[k] for k in ("code", "name_en", "name_mr", "name_hi",
                                                                         "lon", "lat", "source_url")}))
        _add(stats, "districts", ins, upd)
        ins, upd = _count(db.execute(BOUNDARY_UPSERT, {
            "code": d["code"], "geojson": json.dumps(d["boundary"]), "source": d["boundary_source"],
            "source_url": d["boundary_source_url"], "licence": d["boundary_licence"]}))
        _add(stats, "district_boundaries", ins, upd)

    for t in talukas:
        ins, upd = _count(db.execute(TALUKA_UPSERT, {k: t[k] for k in ("code", "district_code", "name_en", "name_mr",
                                                                       "name_hi", "lon", "lat")}))
        _add(stats, "talukas", ins, upd)
    if prune:
        res = db.execute(text("DELETE FROM talukas WHERE NOT (code = ANY(:codes))"),
                         {"codes": [t["code"] for t in talukas]})
        _add(stats, "talukas", dele=res.rowcount)

    # Villages: COPY into a temporary table, then set-based update / insert (/ prune).
    db.execute(text("CREATE TEMP TABLE tmp_villages (taluka_code text, name_en text, name_mr text, name_hi text, "
                    "lat float8, lon float8) ON COMMIT DROP"))
    cur = db.connection().connection.cursor()
    with cur.copy("COPY tmp_villages (taluka_code, name_en, name_mr, name_hi, lat, lon) FROM STDIN") as cp:
        for v in villages:
            cp.write_row((v["taluka_code"], v["name_en"], v["name_mr"], v["name_hi"], float(v["lat"]),
                          float(v["lon"])))
    db.execute(text("CREATE INDEX ON tmp_villages (name_en, lat, lon)"))
    db.execute(text("ANALYZE tmp_villages"))
    upd = db.execute(text(f"""
        UPDATE villages v SET taluka_id = tk.id, name_mr = t.name_mr, name_hi = t.name_hi
        FROM tmp_villages t JOIN talukas tk ON tk.code = t.taluka_code
        WHERE {VILLAGE_KEY} AND (v.taluka_id, v.name_mr, v.name_hi) IS DISTINCT FROM (tk.id, t.name_mr, t.name_hi)
        """)).rowcount
    ins = db.execute(text(f"""
        INSERT INTO villages (taluka_id, name_en, name_mr, name_hi, lat, lon)
        SELECT tk.id, t.name_en, t.name_mr, t.name_hi, t.lat, t.lon
        FROM tmp_villages t JOIN talukas tk ON tk.code = t.taluka_code
        WHERE NOT EXISTS (SELECT 1 FROM villages v WHERE {VILLAGE_KEY})""")).rowcount
    dele = 0
    if prune:
        dele = db.execute(text(f"""
            DELETE FROM villages v WHERE NOT EXISTS (SELECT 1 FROM tmp_villages t WHERE {VILLAGE_KEY})""")).rowcount
    _add(stats, "villages", ins, upd, dele)

    for m in mandis:
        ins, upd = _count(db.execute(MANDI_UPSERT, {k: m[k] for k in ("name", "commodity", "district_code", "lat", "lon",
                                                                      "state", "district_name", "geocode_source")}))
        _add(stats, "mandi_markets", ins, upd)

    keep = []
    for k in kvks:
        params = {"code": k["district_code"], "name": k["name"], "phone": k["phone"], "source_url": k["source_url"],
                  "verified_at": k["verified_at"]}
        row = db.execute(text("""SELECT kc.id, kc.phone, kc.source_url, kc.verified_at::text AS verified_at
                                 FROM kvk_contacts kc JOIN districts d ON d.id = kc.district_id
                                 WHERE d.code = :code AND kc.name = :name"""), params).first()
        if row is None:
            kid = db.execute(text("""INSERT INTO kvk_contacts (district_id, name, phone, source_url, verified_at)
                                     SELECT id, :name, :phone, :source_url, CAST(:verified_at AS date) FROM districts
                                     WHERE code = :code RETURNING id"""), params).scalar_one()
            _add(stats, "kvk_contacts", ins=1)
        else:
            kid = row.id
            if (row.phone, row.source_url, row.verified_at) != (k["phone"], k["source_url"], k["verified_at"]):
                db.execute(text("""UPDATE kvk_contacts SET phone = :phone, source_url = :source_url,
                                   verified_at = CAST(:verified_at AS date) WHERE id = :id"""), params | {"id": kid})
                _add(stats, "kvk_contacts", upd=1)
        keep.append(kid)
    _add(stats, "kvk_contacts")
    if prune:
        res = db.execute(text("DELETE FROM kvk_contacts WHERE source_url = :u AND NOT (id = ANY(:ids))"),
                         {"u": gs.ATARI_KVK_PDF, "ids": keep})
        _add(stats, "kvk_contacts", dele=res.rowcount)
    return stats


def table_counts(db: Session) -> dict[str, int]:
    return {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
            for t in ("districts", "district_boundaries", "talukas", "villages", "mandi_markets", "kvk_contacts")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="regenerate data/geo from the raw cache first")
    ap.add_argument("--refresh", action="store_true", help="re-download every source (implies --rebuild)")
    ap.add_argument("--offline", action="store_true", help="never use the network")
    ap.add_argument("--prune", action="store_true", help="delete rows that are no longer in the files")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    if a.refresh or a.rebuild or not gs.outputs_exist():
        res = gs.build_all(refresh=a.refresh, offline=a.offline)
        print(f"built data/geo: {len(res.districts)} districts, {len(res.talukas)} talukas, "
              f"{len(res.villages)} villages, {len(res.mandis)} mandi rows, {len(res.kvks)} KVKs")
    with session_scope() as db:
        stats = seed(db, prune=a.prune)
        counts = table_counts(db)
    changed = sum(v["inserted"] + v["updated"] + v["deleted"] for v in stats.values())
    for table, s in stats.items():
        print(f"{table:20s} inserted {s['inserted']:6d}  updated {s['updated']:6d}  deleted {s['deleted']:6d}  "
              f"rows now {counts[table]}")
    print(f"{'no changes' if changed == 0 else f'{changed} rows changed'} ({time.monotonic() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
