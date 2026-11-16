"""Retrieval evaluation (PRD §16 day 9; build brief 7.7) on data/rag_eval.jsonl.

Relevance labels are derived from metadata, not hand-judged per chunk: a retrieved chunk is relevant when its crop
matches the question's crop (or the chunk applies to any crop) and its topics intersect the question's topics.
This is stated in docs/RAG_ARCHITECTURE.md. Usage:
    uv run python scripts/eval_rag.py [--compare-embeddings] > ../../docs/RAG_EVAL.md
"""
import argparse
import json
import math
from pathlib import Path

import _bootstrap  # noqa: F401
import numpy as np
from sqlalchemy import select

from app.core.config import DATA_DIR, get_settings
from app.core.db import session_scope
from app.models.tables import AdvisoryChunk, AdvisoryDocument
from app.services.rag import retrieve as rag
from app.services.rag.compose import compose
from app.services.rag.embed import embed
from app.services.rag.ingest import load_manifest
from app.services.voice import intents

K = 5


def relevant(q: dict, crop: str | None, topics: list[str]) -> bool:
    if q["expect"] == "abstain":
        return False
    crop_ok = q["crop"] is None or crop in (q["crop"], None)
    return crop_ok and bool(set(topics) & set(q["topics"]))


def metrics(qs: list[dict], ranked: dict[str, list[tuple[str | None, list[str]]]], totals: dict[str, int]) -> dict:
    p, r, hit, mrr, ndcg = [], [], [], [], []
    for q in qs:
        if q["expect"] != "answer":
            continue
        rels = [relevant(q, c, t) for c, t in ranked[q["id"]][:K]]
        total = totals[q["id"]]
        p.append(sum(rels) / K)
        r.append(sum(rels) / max(1, min(K, total)))
        hit.append(1.0 if any(rels) else 0.0)
        rr = next((1 / (i + 1) for i, x in enumerate(rels) if x), 0.0)
        mrr.append(rr)
        dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(rels) if x)
        idcg = sum(1 / math.log2(i + 2) for i in range(min(K, total))) or 1.0
        ndcg.append(dcg / idcg)
    m = lambda xs: round(float(np.mean(xs)), 3) if xs else None  # noqa: E731
    return {"precision@5": m(p), "recall@5": m(r), "hit_rate@5": m(hit), "mrr": m(mrr), "ndcg@5": m(ndcg), "n": len(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare-embeddings", action="store_true")
    a = ap.parse_args()
    qs = [json.loads(ln) for ln in (DATA_DIR / "rag_eval.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    manifest = {d["document_id"]: d for d in load_manifest()}
    out: dict = {"embedding_model": get_settings().embedding_model, "k": K}
    with session_scope() as db:
        chunks = db.execute(select(AdvisoryChunk.id, AdvisoryChunk.crop, AdvisoryChunk.topics, AdvisoryChunk.content,
                                   AdvisoryChunk.doc_id, AdvisoryChunk.source_url).where(AdvisoryChunk.verified)).all()
        docs = {d.doc_id: d for d in db.execute(select(AdvisoryDocument)).scalars()}
        totals = {q["id"]: sum(1 for c in chunks if relevant(q, c.crop, list(c.topics or []))) for q in qs}
        ranked, crop_rel, cite_ok, cite_n, abst_ok, e2e_ok, rows = {}, [], 0, 0, 0, 0, []
        for q in qs:
            hits = rag.search(db, q["q"], crop=q["crop"], k=K)
            ranked[q["id"]] = [(h.crop, h.topics) for h in hits]
            above = rag.above_threshold(hits)
            intent = intents.resolve(q["q"])
            abstained = (not intent.agricultural) or not above
            abst_ok += int(abstained == (q["expect"] == "abstain"))
            # end to end: does the composer turn the retrieved passages into a quoted answer?
            comp = None if abstained else compose(q["q"], q["lang"], [], above, intro="", crop=q["crop"] or intent.crop)
            composed = bool(comp and not comp.abstain)
            e2e_ok += int((not composed) == (q["expect"] == "abstain"))
            for h in hits:
                cite_n += 1
                m = manifest.get(h.doc_id)
                d = docs.get(h.doc_id)
                path_ok = bool(m) and (DATA_DIR / "corpus" / m["local_path"]).exists()
                cite_ok += int(bool(m and d and h.source_url == m["source_url"] == d.source_url and path_ok))
            if q["crop"]:
                crop_rel += [1.0 if h.crop in (q["crop"], None) else 0.0 for h in hits]
            rows.append({"id": q["id"], "lang": q["lang"], "expect": q["expect"], "abstained": abstained, "composed": composed,
                         "quote": comp.quotes[0]["text"][:110] if composed and comp.quotes else None,
                         "top1": f"{hits[0].institution}: {hits[0].title[:60]}" if hits else None,
                         "top1_similarity": round(hits[0].similarity, 3) if hits else None,
                         "relevant_in_top5": sum(relevant(q, c, t) for c, t in ranked[q["id"]][:K])})
        out["hybrid"] = metrics(qs, ranked, totals)
        out["citation_correctness"] = round(cite_ok / cite_n, 3) if cite_n else None
        out["crop_relevance@5"] = round(float(np.mean(crop_rel)), 3) if crop_rel else None
        out["stage_relevance"] = "n/a (no stage-labelled questions in this set)"
        out["abstention_accuracy"] = round(abst_ok / len(qs), 3)
        n_answer = sum(1 for q in qs if q["expect"] == "answer")
        out["composed_answer_rate"] = round(sum(r["composed"] for r in rows if r["expect"] == "answer") / n_answer, 3) if n_answer else None
        out["end_to_end_abstention_accuracy"] = round(e2e_ok / len(qs), 3)
        out["verified_chunks"] = len(chunks)
        out["questions"] = rows
        if a.compare_embeddings and chunks:
            texts = [c.content for c in chunks]
            out["vector_only"] = {}
            for name in ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                         "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"):
                cv = embed(texts, name)
                rk = {}
                for q in qs:
                    sims = cv @ embed([q["q"]], name)[0]
                    order = [i for i in np.argsort(-sims) if q["crop"] is None or chunks[i].crop in (q["crop"], None)][:K]
                    rk[q["id"]] = [(chunks[i].crop, list(chunks[i].topics or [])) for i in order]
                out["vector_only"][name] = metrics(qs, rk, totals)
    print("# RAG retrieval evaluation\n")
    print(f"Embedding model: `{out['embedding_model']}`. Verified chunks searched: {out['verified_chunks']}. K = {K}.\n")
    print("Relevance labels are metadata-derived (crop match and topic overlap), not per-chunk human judgements.\n")
    print("| Metric | Hybrid (vector + FTS, RRF) |\n|---|---|")
    for k, v in out["hybrid"].items():
        print(f"| {k} | {v} |")
    for k in ("citation_correctness", "crop_relevance@5", "stage_relevance", "abstention_accuracy"):
        print(f"| {k} | {out[k]} |")
    print("\n## End to end (retrieval, then the deterministic composer)\n")
    print("`abstention_accuracy` above checks the retrieval gate only. Here the composer must also find a quotable sentence that "
          "shares a topic word with the question, passes the dose, crop, citation-text and PDF-Devanagari guards, and "
          "survives the number validator.\n")
    print(f"| Metric | Value |\n|---|---|\n| composed_answer_rate (answerable questions) | {out['composed_answer_rate']} |\n"
          f"| end_to_end_abstention_accuracy | {out['end_to_end_abstention_accuracy']} |")
    if out.get("vector_only"):
        print("\n## Embedding model comparison (vector-only retrieval)\n\n| Model | P@5 | Hit@5 | MRR | nDCG@5 |\n|---|---|---|---|---|")
        for name, m in out["vector_only"].items():
            print(f"| `{name}` | {m['precision@5']} | {m['hit_rate@5']} | {m['mrr']} | {m['ndcg@5']} |")
    print("\n## Per question\n\n| id | lang | expected | retrieval abstained | composed | relevant in top 5 | top-1 similarity | top-1 source | first quote |\n|---|---|---|---|---|---|---|---|---|")
    for r in out["questions"]:
        quote = " ".join((r["quote"] or "").replace("|", "/").split())
        print(f"| {r['id']} | {r['lang']} | {r['expect']} | {r['abstained']} | {r['composed']} | {r['relevant_in_top5']} | {r['top1_similarity']} | {r['top1']} | {quote} |")
    Path(DATA_DIR / "rag_eval_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
