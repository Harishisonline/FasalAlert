"""Filtered vector search must work on the PRD's ivfflat index (lists=100) built on an empty table."""
import numpy as np

from app.models.tables import AdvisoryChunk
from app.services.rag import retrieve


def test_filtered_vector_search_finds_rare_crop(db, monkeypatch):
    rng = np.random.default_rng(1)
    vecs = rng.normal(size=(300, 768)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    for i, v in enumerate(vecs):
        crop = "soybean" if i in (7, 150, 299) else "cotton"
        db.add(AdvisoryChunk(doc_id=f"d{i}", institution="ICAR-TEST", title=f"t{i}", source_url="https://example.org", license="x",
                             verified=True, embedding=v.tolist(), content=f"advice text number {i} about field practice",
                             crop=crop, content_hash=f"h{i}"))
    db.commit()
    monkeypatch.setattr(retrieve, "embed_one", lambda q: vecs[150])
    hits = retrieve.search(db, "zzqx", crop="soybean", k=3)
    assert hits and hits[0].title == "t150" and "vector#1" in hits[0].why
    assert {h.crop for h in hits} <= {"soybean", None}
