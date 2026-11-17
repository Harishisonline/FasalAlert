#!/usr/bin/env python3
"""Fetch the embedding model into the function bundle at build time.

The deployed API embeds queries with the int8 ONNX build of
sentence-transformers/paraphrase-multilingual-mpnet-base-v2 (Apache-2.0, 768 dims). The weights
are about 278 MB, so they are downloaded here instead of being committed to the repository.

The Hugging Face cache layout duplicates every blob (blobs/ plus a snapshots/ copy), which made a
function bundle several times larger than the model itself. This script writes a flat directory
instead: one copy of the model plus its tokenizer, which app/services/rag/embed.py loads directly.

Run from the repository root:
    python apps/api/scripts/fetch_embedding_model.py

The script is idempotent: files that are already present with the expected checksum are kept.
"""
from __future__ import annotations

import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "apps" / "api" / "data" / "models" / "mpnet-int8"
BASE_URL = "https://huggingface.co/Xenova/paraphrase-multilingual-mpnet-base-v2/resolve/main"

# Remote path -> (path inside the flat model directory, expected sha256)
FILES: dict[str, tuple[str, str]] = {
    "onnx/model_int8.onnx": ("onnx/model.onnx", "584747771eca8569acad184873dfb775d9b707ddbbb4da552bf80ee7d2ca9674"),
    "tokenizer.json": ("tokenizer.json", "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441"),
    "tokenizer_config.json": ("tokenizer_config.json", "efb5c0d09722e5fe59a462cd2a9976ee216d55b037597d997cd3fe833216da15"),
    "special_tokens_map.json": ("special_tokens_map.json", "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f"),
    "config.json": ("config.json", "14533f158fb2476510b3a83256386b983daa8cfa799ea35217c89947be63835e"),
}

USER_AGENT = "FasalAlert-build/1.0 (+https://github.com/Harishisonline/FasalAlert)"
ATTEMPTS = 3


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(remote: str, dest: Path) -> None:
    """Download one file, retrying transient failures."""
    url = f"{BASE_URL}/{remote}"
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=180) as response, dest.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:  # noqa: PERF203 - retry loop
            last = exc
            print(f"  attempt {attempt}/{ATTEMPTS} failed for {remote}: {exc}", flush=True)
            dest.unlink(missing_ok=True)
            time.sleep(3 * attempt)
    raise SystemExit(f"could not download {url}: {last}")


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for remote, (relative, expected) in FILES.items():
        dest = MODEL_DIR / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and sha256(dest) == expected:
            print(f"  keep    {relative} ({dest.stat().st_size} bytes)", flush=True)
            total += dest.stat().st_size
            continue
        started = time.time()
        download(remote, dest)
        digest = sha256(dest)
        if digest != expected:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"checksum mismatch for {remote}: expected {expected}, got {digest}")
        size = dest.stat().st_size
        total += size
        print(f"  fetched {relative} ({size} bytes in {time.time() - started:.1f}s)", flush=True)
    print(f"embedding model ready in {MODEL_DIR} ({total} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
