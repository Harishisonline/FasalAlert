"""Recompute crop, stage and topic tags of stored chunks with the current rules, without re-embedding."""
import _bootstrap  # noqa: F401
from sqlalchemy import select

from app.core.db import session_scope
from app.models.tables import AdvisoryChunk
from app.services.rag.ingest import _stage_tags, chunk_crop, crop_keys, doc_topics, load_manifest
from app.services.rag.vocab import topics_in

manifest = {d["document_id"]: d for d in load_manifest()}
changed = 0
with session_scope() as db:
    for c in db.execute(select(AdvisoryChunk)).scalars():
        doc = manifest.get(c.doc_id, {})
        new = (chunk_crop(c.content, crop_keys(doc)), _stage_tags(c.content), sorted(topics_in(c.content) or doc_topics(doc)))
        if (c.crop, c.stage, list(c.topics or [])) != new:
            c.crop, c.stage, c.topics = new
            changed += 1
print(f"chunks retagged: {changed}")
