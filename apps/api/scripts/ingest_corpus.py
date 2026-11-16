"""Build the advisory index from apps/api/data/corpus/manifest.jsonl. Usage: uv run python scripts/ingest_corpus.py"""
import json
import sys

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from app.core.db import session_scope
from app.models.tables import AdvisoryChunk, AdvisoryDocument
from app.services.rag.ingest import ingest_all

only = set(sys.argv[1:]) or None
with session_scope() as db:
    rep = ingest_all(db, only=only)
    total = db.execute(select(func.count()).select_from(AdvisoryChunk)).scalar_one()
    verified = db.execute(select(func.count()).select_from(AdvisoryChunk).where(AdvisoryChunk.verified)).scalar_one()
    docs = db.execute(select(func.count()).select_from(AdvisoryDocument)).scalar_one()
    by_crop = dict(db.execute(select(AdvisoryChunk.crop, func.count()).where(AdvisoryChunk.verified).group_by(AdvisoryChunk.crop)).all())
    by_lang = dict(db.execute(select(AdvisoryChunk.lang, func.count()).where(AdvisoryChunk.verified).group_by(AdvisoryChunk.lang)).all())
print(json.dumps({"run": rep.__dict__, "documents": docs, "chunks": total, "verified_chunks": verified,
                  "verified_by_crop": {str(k): v for k, v in by_crop.items()}, "verified_by_lang": by_lang}, indent=1, ensure_ascii=False))
