"""AGMARKNET mandi prices and arrivals via data.gov.in (Government open data; API key required),
plus an importer for official AGMARKNET report exports (CSV) when the API is unavailable.

No price is ever fabricated. Rows carry source, source URL, fetch time and licence. Seeded synthetic
rows (PRD §10.1) use source='synthetic_seed' and are excluded from model training.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tables import MandiMarket, MandiPrice
from app.services.foundry.http import UpstreamError, get_json, ingest_run

LICENCE = "Government Open Data License - India (data.gov.in)"
API_SOURCE = "agmarknet-datagovin"
CSV_SOURCE = "agmarknet-export"
SYNTHETIC = "synthetic_seed"


class NotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class PriceRecord:
    state: str
    district: str
    market: str
    commodity: str
    price_date: date
    min_rs_qtl: float | None
    max_rs_qtl: float | None
    modal_rs_qtl: float | None
    arrival_qtl: float | None


def _num(v: object) -> float | None:
    if v in (None, "", "NR", "-"):
        return None
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return x if x > 0 else None  # AGMARKNET uses 0 for "not reported"; never treat it as a price


def _date(v: str) -> date:
    v = v.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {v!r}")


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z]", "", k.lower().replace("_x0020_", ""))


def parse_record(raw: dict[str, object]) -> PriceRecord | None:
    r = {_norm_key(k): v for k, v in raw.items()}
    try:
        d = _date(str(r.get("arrivaldate") or r.get("pricedate") or r.get("date")))
    except ValueError:
        return None
    modal = _num(r.get("modalprice") or r.get("modalpricersquintal"))
    if modal is None:
        return None
    return PriceRecord(
        state=str(r.get("state") or "").strip(), district=str(r.get("district") or r.get("districtname") or "").strip(),
        market=str(r.get("market") or r.get("marketname") or "").strip(), commodity=str(r.get("commodity") or "").strip(),
        price_date=d, min_rs_qtl=_num(r.get("minprice") or r.get("minpricersquintal")),
        max_rs_qtl=_num(r.get("maxprice") or r.get("maxpricersquintal")), modal_rs_qtl=modal,
        arrival_qtl=_num(r.get("arrivals") or r.get("arrivalstonnes") or r.get("arrival")),
    )


def fetch_current(commodity: str, state: str = "Maharashtra", limit: int = 1000) -> tuple[list[PriceRecord], str]:
    s = get_settings()
    if not s.data_gov_in_api_key:
        raise NotConfigured("DATA_GOV_IN_API_KEY is not set (register at https://data.gov.in)")
    url = f"https://api.data.gov.in/resource/{s.agmarknet_resource_id}"
    out: list[PriceRecord] = []
    offset = 0
    while True:
        data = get_json(url, {"api-key": s.data_gov_in_api_key, "format": "json", "limit": limit, "offset": offset,
                              "filters[state.keyword]": state, "filters[commodity]": commodity})
        recs = data.get("records", [])
        out += [p for p in (parse_record(r) for r in recs) if p]
        offset += len(recs)
        if not recs or offset >= int(data.get("total", 0) or 0):
            break
    return out, url


def _market(db: Session, rec: PriceRecord) -> MandiMarket:
    m = db.execute(select(MandiMarket).where(MandiMarket.name == rec.market, MandiMarket.commodity == rec.commodity)).scalar_one_or_none()
    if m is None:
        m = MandiMarket(name=rec.market, commodity=rec.commodity, state=rec.state or None, district_name=rec.district or None)
        db.add(m)
        db.flush()
    return m


def store(db: Session, recs: list[PriceRecord], source: str, source_url: str, fetched_at: datetime | None = None) -> int:
    if source == SYNTHETIC:
        raise ValueError("use scripts/seed_mandi.py for synthetic rows")
    n = 0
    for rec in recs:
        m = _market(db, rec)
        stmt = insert(MandiPrice).values(
            market_id=m.id, commodity=rec.commodity, price_date=rec.price_date, min_rs_qtl=rec.min_rs_qtl,
            max_rs_qtl=rec.max_rs_qtl, modal_rs_qtl=rec.modal_rs_qtl, arrival_qtl=rec.arrival_qtl,
            source=source, source_url=source_url, licence=LICENCE, **({"fetched_at": fetched_at} if fetched_at else {}),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["market_id", "commodity", "price_date"],
            set_={"min_rs_qtl": stmt.excluded.min_rs_qtl, "max_rs_qtl": stmt.excluded.max_rs_qtl,
                  "modal_rs_qtl": stmt.excluded.modal_rs_qtl, "arrival_qtl": stmt.excluded.arrival_qtl,
                  "source": stmt.excluded.source, "source_url": stmt.excluded.source_url,
                  "licence": stmt.excluded.licence, "fetched_at": stmt.excluded.fetched_at},
        )  # real data replaces any synthetic seed row for the same market and date
        db.execute(stmt)
        n += 1
    return n


def ingest_current(db: Session, commodities: list[str]) -> dict[str, int | str]:
    out: dict[str, int | str] = {}
    for c in commodities:
        with ingest_run(db, "agmarknet", commodity=c) as run:
            try:
                recs, url = fetch_current(c)
            except NotConfigured as e:
                run.status, run.error = "skipped", str(e)
                out[c] = "not_configured"
                continue
            except UpstreamError as e:
                run.status, run.error = "failed", str(e)
                out[c] = "failed"
                continue
            run.records = store(db, recs, API_SOURCE, url)
            out[c] = run.records
    return out


def import_csv(db: Session, path: Path, source_url: str, retrieved_at: datetime, state_filter: str | None = "Maharashtra") -> int:
    """Import an official AGMARKNET report export. The origin URL and retrieval date are required
    so every row keeps its provenance (docs/DATA_PROVENANCE.md)."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    recs = [p for p in (parse_record(r) for r in reader) if p and (not state_filter or not p.state or p.state == state_filter)]
    with ingest_run(db, "agmarknet-csv", file=path.name, source_url=source_url) as run:
        run.records = store(db, recs, CSV_SOURCE, source_url, fetched_at=retrieved_at)
    return run.records
