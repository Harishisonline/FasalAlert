"""Hybrid retrieval: pgvector cosine similarity + PostgreSQL full-text search, fused with Reciprocal
Rank Fusion (k=60), then metadata boosts for crop, stage and topic. Only verified chunks are searched.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.rag.embed import embed_one
from app.services.rag.vocab import STOPWORDS, expand_query

RRF_K = 60


@dataclass
class Hit:
    id: int
    doc_id: str
    institution: str
    title: str
    year: int | None
    source_url: str
    license: str
    lang: str
    crop: str | None
    stage: str | None
    topics: list[str]
    content: str
    page: int | None
    similarity: float = 0.0           # cosine similarity of the vector match (0 if only FTS matched)
    fts_rank: float = 0.0
    score: float = 0.0                # fused score
    why: list[str] = field(default_factory=list)


_COLS = "id, doc_id, institution, title, year, source_url, license, lang, crop, stage, topics, content, page"


def _row(r) -> Hit:  # type: ignore[no-untyped-def]
    return Hit(r.id, r.doc_id, r.institution, r.title, r.year, r.source_url, r.license, r.lang, r.crop, r.stage,
               list(r.topics or []), r.content, r.page)


def search(
    db: Session, query: str, crop: str | None = None, stage: str | None = None, topic: str | None = None,
    k: int = 5, pool: int = 30,
) -> list[Hit]:
    expanded = expand_query(query)
    # Embed the expanded query too: canonical English terms appended to a Marathi or Hindi question raise
    # cross-lingual similarity against the mostly English sources.
    q_vec = embed_one(expanded).tolist()
    crop_filter = "AND (crop = :crop OR crop IS NULL)" if crop else ""
    params = {"q": str(q_vec), "pool": pool, "crop": crop, "tsq": expanded}
    # The PRD's ivfflat index has lists=100. With default probes=1 a filtered query sees about 1 % of the corpus
    # and can return nothing. Search every list (exact at this corpus size) and let pgvector keep scanning
    # until the filter is satisfied.
    db.execute(text("SET LOCAL ivfflat.probes = 100"))
    db.execute(text("SET LOCAL ivfflat.iterative_scan = relaxed_order"))
    vec_rows = db.execute(text(f"""
        SELECT {_COLS}, 1 - (embedding <=> CAST(:q AS vector)) AS sim
        FROM advisory_chunks WHERE verified AND embedding IS NOT NULL {crop_filter}
        ORDER BY embedding <=> CAST(:q AS vector) LIMIT :pool"""), params).all()
    fts_rows = db.execute(text(f"""
        SELECT {_COLS}, ts_rank_cd(content_tsv, websearch_to_tsquery('simple', :tsq)) AS rank
        FROM advisory_chunks
        WHERE verified AND content_tsv @@ websearch_to_tsquery('simple', :tsq) {crop_filter}
        ORDER BY rank DESC LIMIT :pool"""), params).all()
    if not fts_rows:  # websearch_to_tsquery ANDs terms; retry as OR for long spoken questions
        terms = [t for t in expanded.replace('"', " ").split()
                 if len(t) > 2 and t.lower().strip("?,.!।") not in STOPWORDS][:24]
        if terms:
            params["tsq"] = " or ".join(terms)
            fts_rows = db.execute(text(f"""
                SELECT {_COLS}, ts_rank_cd(content_tsv, websearch_to_tsquery('simple', :tsq)) AS rank
                FROM advisory_chunks
                WHERE verified AND content_tsv @@ websearch_to_tsquery('simple', :tsq) {crop_filter}
                ORDER BY rank DESC LIMIT :pool"""), params).all()
    hits: dict[int, Hit] = {}
    for rank, r in enumerate(vec_rows):
        h = hits.setdefault(r.id, _row(r))
        h.similarity = float(r.sim)
        h.score += 1.0 / (RRF_K + rank + 1)
        h.why.append(f"vector#{rank + 1}")
    for rank, r in enumerate(fts_rows):
        h = hits.setdefault(r.id, _row(r))
        h.fts_rank = float(r.rank)
        h.score += 1.0 / (RRF_K + rank + 1)
        h.why.append(f"fts#{rank + 1}")
    for h in hits.values():
        if crop and h.crop == crop:
            h.score *= 1.15
            h.why.append("crop")
        if stage and h.stage == stage:
            h.score *= 1.10
            h.why.append("stage")
        if topic and topic in h.topics:
            h.score *= 1.15
            h.why.append("topic")
    ranked = sorted(hits.values(), key=lambda h: h.score, reverse=True)
    if ranked and any(h.similarity == 0.0 for h in ranked[:k]):
        # FTS-only hits lack a similarity; compute it so the abstention threshold applies to every hit.
        missing = [h for h in ranked[:k] if h.similarity == 0.0]
        ids = [h.id for h in missing]
        rows = db.execute(text("SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM advisory_chunks WHERE id = ANY(:ids)"),
                          {"q": str(q_vec), "ids": ids}).all()
        sims = {r.id: float(r.sim) for r in rows}
        for h in missing:
            h.similarity = sims.get(h.id, 0.0)
    return ranked[:k]


def above_threshold(hits: list[Hit]) -> list[Hit]:
    """Abstention gate on cosine similarity only. RRF scores are rank-based and carry no absolute relevance,
    so they are used for ordering, never for the accept/abstain decision."""
    s = get_settings()
    return [h for h in hits if h.similarity >= s.rag_min_similarity]
