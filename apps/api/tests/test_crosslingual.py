"""PRD AC 15: an English question about Marathi content returns the Marathi chunk. Uses the real local embedding
model (fastembed ONNX, cached under data/cache). The chunk texts are TEST FIXTURES written for this test."""
from app.models.tables import AdvisoryChunk
from app.services.rag import retrieve
from app.services.rag.embed import embed

CHUNKS = [
    ("mr", "mango", "थंडीच्या रात्री आंब्याच्या मोहोराचे दंवापासून संरक्षण करण्यासाठी संध्याकाळी बागेला हलके पाणी द्यावे आणि बागेत धूर करावा."),
    ("en", "cotton", "Pink bollworm infestation in cotton increases late in the season; install pheromone traps at five per hectare."),
    ("en", "sugarcane", "Sugarcane setts are planted in trenches 30 cm deep and covered with a thin layer of soil after planting."),
    ("en", "soybean", "Soybean should be sown on broad bed and furrow ridges so that excess rain water drains from the field."),
]


def test_english_question_finds_the_marathi_chunk(db):
    vecs = embed([c[2] for c in CHUNKS])
    for i, ((lang, crop, text), v) in enumerate(zip(CHUNKS, vecs, strict=True)):
        db.add(AdvisoryChunk(doc_id=f"x{i}", institution="ICAR-TEST", title=f"fixture {i}", source_url="https://example.org",
                             license="x", verified=True, embedding=v.tolist(), content=text, lang=lang, crop=crop,
                             content_hash=f"x{i}"))
    db.commit()
    hits = retrieve.search(db, "How do I protect mango flowers from frost on cold nights?", k=3)
    assert hits and hits[0].lang == "mr" and hits[0].crop == "mango"
    assert hits[0].similarity >= 0.45   # passes the abstention gate on similarity alone
