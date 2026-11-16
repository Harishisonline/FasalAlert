"""Advisory corpus ingestion (PRD §9.4): manifest -> validate source -> extract -> clean -> detect language
-> chunk -> deduplicate -> tag crop/stage/topic -> embed -> store (pgvector + generated tsvector).

Only documents from trusted institutions with recorded provenance are marked verified; only verified
chunks are retrievable. Retrieved text is treated as data, never as instructions (PRD §12).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR, get_settings
from app.models.tables import AdvisoryChunk, AdvisoryDocument
from app.services.foundry.http import ingest_run
from app.services.rag import text as T
from app.services.rag.embed import embed
from app.services.rag.vocab import crops_in, topics_in

log = logging.getLogger("fasalalert.rag")
CORPUS_DIR = DATA_DIR / "corpus"
CROP_KEYS = {"mango", "pomegranate", "grape", "soybean", "cotton", "sugarcane"}
TRUSTED_PREFIXES = ("ICAR", "KVK", "IMD", "FAO", "MPKV", "PDKV", "DR. PDKV", "VNMKV", "BSKKV", "DR. BSKKV",
                    "MAHARASHTRA", "GOVERNMENT OF MAHARASHTRA", "DEPARTMENT OF AGRICULTURE", "MINISTRY OF AGRICULTURE",
                    "ATARI", "NHB", "NATIONAL HORTICULTURE BOARD", "TNAU", "MAHAGRAPES", "APEDA")


@dataclass
class IngestReport:
    documents: int = 0
    skipped: int = 0
    chunks: int = 0
    duplicates: int = 0
    unverified: int = 0
    skipped_licence: list[str] | None = None
    errors: list[str] | None = None


MANIFEST_TOPICS = {  # corpus manifest vocabulary -> retrieval topic keys (rag/vocab.py)
    "pest_management": "pest_disease", "disease_management": "pest_disease", "seasonal_practices": "cultivation",
    "growth_stages": "growth_stage", "heavy_rain_waterlogging": "rainfall_management", "post_harvest_storage": "storage",
    "drought": "irrigation", "frost_protection": "frost_protection", "heat_stress": "heat_stress", "irrigation": "irrigation",
    "harvesting": "harvesting", "transport": "transport",
}


def doc_topics(doc: dict[str, Any]) -> set[str]:
    return {MANIFEST_TOPICS.get(t, t) for t in doc.get("topics", [])}


def crop_keys(doc: dict[str, Any]) -> list[str]:
    """Specific crops of a document; a document marked "general" applies to every crop."""
    crops = doc.get("crops", [])
    return [] if "general" in crops else [c for c in crops if c in CROP_KEYS]


def chunk_crop(text: str, doc_crops: list[str]) -> str | None:
    """A general document's chunks apply to every crop (NULL), even when an example mentions one crop."""
    if not doc_crops:
        return None
    if len(doc_crops) == 1:
        return doc_crops[0]
    mentioned = crops_in(text) & set(doc_crops)
    return next(iter(mentioned)) if len(mentioned) == 1 else None


def is_trusted(institution: str) -> bool:
    u = institution.upper().strip()
    return any(u.startswith(p) or p in u for p in TRUSTED_PREFIXES)


def load_manifest(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or CORPUS_DIR / "manifest.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _stage_tags(text: str) -> str | None:
    from app.services.rag.vocab import alias_index

    low = text.lower()
    hits: dict[str, int] = {}
    for alias, (canon, cat) in alias_index().items():
        if cat == "stage" and len(alias) > 3 and alias in low:
            hits[canon] = hits.get(canon, 0) + low.count(alias)
    return max(hits, key=lambda k: hits[k]) if hits else None


def ingest_document(db: Session, doc: dict[str, Any], seen: list[set[str]]) -> tuple[int, int]:
    path = CORPUS_DIR / doc["local_path"]
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if doc.get("sha256") and doc["sha256"] != sha:
        raise ValueError(f"{doc['document_id']}: sha256 mismatch, file changed since acquisition")
    trusted = is_trusted(doc["institution"])
    # Retrievable only when the institution is trusted AND the reuse licence is verified (build brief 7.1).
    verified = bool(trusted and doc.get("source_url") and doc.get("licence_verified"))
    pages = T.clean_pages(T.extract(path))
    full = "\n\n".join(p.text for p in pages)
    lang = doc.get("language") or T.detect_language(full)
    chunks = T.chunk_text(pages)
    doc_crops = crop_keys(doc)   # "general" = applies to any crop (crop NULL)
    db.merge(AdvisoryDocument(
        doc_id=doc["document_id"], institution=doc["institution"], title=doc["source_title"],
        source_url=doc["source_url"], landing_url=doc.get("landing_url"), year=doc.get("publication_year"),
        crops=doc_crops, topics=doc.get("topics", []), lang=lang, license=doc.get("licence") or "unknown",
        license_evidence_url=doc.get("licence_evidence_url"), license_verified=bool(doc.get("licence_verified")),
        sha256=sha, local_path=doc["local_path"],
        retrieved_at=datetime.fromisoformat(doc["retrieved_at"]) if doc.get("retrieved_at") else None,
        verified=verified,
    ))
    db.execute(delete(AdvisoryChunk).where(AdvisoryChunk.doc_id == doc["document_id"]))
    kept: list[tuple[str, int | None, str]] = []
    dups = 0
    existing = {h for (h,) in db.execute(select(AdvisoryChunk.content_hash))}
    for text, page in chunks:
        h = T.content_hash(text)
        sh = T.shingles(text)
        if h in existing or any(T.near_duplicate(sh, s) for s in seen[-400:]):
            dups += 1
            continue
        existing.add(h)
        seen.append(sh)
        kept.append((text, page, h))
    if not kept:
        return 0, dups
    model = get_settings().embedding_model
    vecs = embed([k[0] for k in kept])
    for i, ((text, page, h), v) in enumerate(zip(kept, vecs, strict=True)):
        crop = chunk_crop(text, doc_crops)
        db.add(AdvisoryChunk(
            doc_id=doc["document_id"], institution=doc["institution"], title=doc["source_title"],
            year=doc.get("publication_year"), lang=T.detect_language(text) if lang != "en" else "en",
            crop=crop, stage=_stage_tags(text), source_url=doc["source_url"],
            license=doc.get("licence") or "unknown", verified=verified, embedding=v.tolist(), content=text,
            chunk_index=i, topics=sorted(topics_in(text) or doc_topics(doc)),
            content_hash=h, embedding_model=model, page=page,
        ))
    db.flush()
    return len(kept), dups


def ingest_all(db: Session, manifest: Path | None = None, only: set[str] | None = None) -> IngestReport:
    rep = IngestReport(errors=[], skipped_licence=[])
    seen: list[set[str]] = []
    docs = load_manifest(manifest)
    with ingest_run(db, "advisory-corpus", documents=len(docs)) as run:
        for doc in docs:
            if only and doc["document_id"] not in only:
                continue
            if not doc.get("text_extractable", True):
                rep.skipped += 1
                continue
            if not doc.get("licence_verified"):
                # Build brief 7.1: only index documents whose source and licence can be verified. These stay in the
                # manifest and are indexed once the publisher's permission is recorded (licence_verified: true).
                rep.skipped_licence.append(doc["document_id"])  # type: ignore[union-attr]
                continue
            try:
                n, d = ingest_document(db, doc, seen)
                db.commit()
            except Exception as e:  # noqa: BLE001 - one bad document must not stop the corpus build
                db.rollback()
                rep.errors.append(f"{doc.get('document_id')}: {e}")  # type: ignore[union-attr]
                rep.skipped += 1
                continue
            rep.documents += 1
            rep.chunks += n
            rep.duplicates += d
            if not (is_trusted(doc["institution"]) and doc.get("licence_verified")):
                rep.unverified += n
        run.records = rep.chunks
    # ivfflat centroids are computed at index build time; rebuild once data exists (the PRD creates the index
    # on an empty table, which leaves it untrained).
    from sqlalchemy import text as sql_text

    db.execute(sql_text("REINDEX INDEX idx_chunks_ivfflat"))
    db.commit()
    return rep
