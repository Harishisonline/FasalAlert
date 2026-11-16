"""Local multilingual sentence embeddings (ONNX via fastembed). No external API at inference time.

Default: sentence-transformers/paraphrase-multilingual-mpnet-base-v2 (Apache-2.0, 768 dims, trained on
parallel data covering 50+ languages including Marathi and Hindi). The choice is evaluated against
paraphrase-multilingual-MiniLM-L12-v2 in scripts/eval_rag.py; see docs/RAG_ARCHITECTURE.md.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from app.core.config import DATA_DIR, get_settings


@lru_cache(maxsize=2)
def _model(name: str):  # type: ignore[no-untyped-def]
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=name, cache_dir=str(DATA_DIR / "cache" / "fastembed"))


def embed(texts: list[str], model_name: str | None = None, batch_size: int = 16) -> np.ndarray:
    name = model_name or get_settings().embedding_model
    vecs = np.array(list(_model(name).embed(texts, batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-9)


def embed_one(text: str, model_name: str | None = None) -> np.ndarray:
    return embed([text], model_name)[0]
