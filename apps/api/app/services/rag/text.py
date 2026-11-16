"""Text extraction, cleaning, language detection and chunking for the advisory corpus."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
# Function words that separate Marathi from Hindi in Devanagari text.
MR_MARKERS = {"आहे", "आहेत", "आणि", "करावी", "करावे", "करणे", "मध्ये", "साठी", "पासून", "नाही", "असे", "हे", "व", "च्या", "ची", "चा", "चे", "ळ"}
HI_MARKERS = {"है", "हैं", "और", "करें", "करना", "में", "लिए", "से", "नहीं", "यह", "का", "की", "के", "को", "पर"}


@dataclass(frozen=True)
class Page:
    number: int | None
    text: str


def extract(path: Path) -> list[Page]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [Page(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
    if suffix in (".html", ".htm"):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript", "aside"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        blocks = [el.get_text(" ", strip=True) for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "td"])]
        return [Page(None, "\n\n".join(b for b in blocks if b))]
    if suffix == ".jsonl":
        pages = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                obj = json.loads(line)
                pages.append(Page(obj.get("page", i + 1), obj.get("content") or obj.get("text") or ""))
        return pages
    return [Page(None, path.read_text(encoding="utf-8", errors="replace"))]  # .txt, .md


_CONS = "\u0915-\u0939\u0958-\u095f"


def fix_devanagari(t: str) -> str:
    """Repair common legacy-font PDF extraction artefacts in Devanagari, conservatively:
    a duplicated aa-sign after the vowel aa or another aa-sign (आांबा -> आंबा), and a pre-base i-sign that
    was extracted before its consonant at the start of a word (िक -> कि)."""
    t = re.sub("\u0906\u093e", "\u0906", t)          # आा -> आ
    t = re.sub("\u093e\u093e+", "\u093e", t)          # ाा -> ा
    t = re.sub(f"(?<![{_CONS}\u093c])\u093f([{_CONS}])", "\\1\u093f", t)  # word-initial ि before a consonant
    return t


def clean_pages(pages: list[Page]) -> list[Page]:
    """Normalise Unicode, fix hyphenation, and drop running headers/footers repeated on many pages."""
    norm = [Page(p.number, fix_devanagari(unicodedata.normalize("NFC", p.text))) for p in pages]
    line_counts = Counter(
        ln.strip() for p in norm for ln in set(p.text.splitlines()) if 3 <= len(ln.strip()) <= 80
    )
    repeated = {ln for ln, c in line_counts.items() if len(norm) >= 4 and c >= max(3, len(norm) // 2)}
    out = []
    for p in norm:
        lines = [ln for ln in p.text.splitlines() if ln.strip() not in repeated and not re.fullmatch(r"\s*\d{1,3}\s*", ln)]
        t = "\n".join(lines)
        t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)            # de-hyphenate across line breaks
        t = re.sub(r"[ \t ]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        out.append(Page(p.number, t.strip()))
    return out


def detect_language(text: str) -> str:
    deva = len(DEVANAGARI.findall(text))
    latin = len(LATIN.findall(text))
    if deva == 0 or latin > deva * 2:
        return "en"
    words = set(re.findall(r"[ऀ-ॿ]+", text))
    mr = sum(1 for w in words if w in MR_MARKERS) + text.count("ळ")
    hi = sum(1 for w in words if w in HI_MARKERS)
    return "mr" if mr >= hi else "hi"


_SENT = re.compile(r"(?<=[.!?।])\s+(?=[A-Z0-9ऀ-ॿ(\"'])")


def sentences(text: str) -> list[str]:
    parts = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if para:
            parts += [s.strip() for s in _SENT.split(para) if s.strip()]
    return parts


def chunk_text(pages: list[Page], target_words: int = 160, max_words: int = 240, overlap_sentences: int = 1) -> list[tuple[str, int | None]]:
    """Sentence-aware chunks of about target_words, with one sentence of overlap. Returns (text, page)."""
    chunks: list[tuple[str, int | None]] = []
    buf: list[str] = []
    buf_page: int | None = None
    count = 0
    for page in pages:
        for s in sentences(page.text):
            w = len(s.split())
            if w > max_words:  # very long table rows or run-on text: hard split
                for i in range(0, w, max_words):
                    piece = " ".join(s.split()[i:i + max_words])
                    chunks.append((piece, page.number))
                continue
            if buf_page is None:
                buf_page = page.number
            buf.append(s)
            count += w
            if count >= target_words:
                chunks.append((" ".join(buf), buf_page))
                buf = buf[-overlap_sentences:] if overlap_sentences else []
                count = sum(len(x.split()) for x in buf)
                buf_page = page.number
    if buf and count >= 25:
        chunks.append((" ".join(buf), buf_page))
    return [(t, p) for t, p in chunks if len(t.split()) >= 25 and _mostly_text(t)]


def _mostly_text(t: str) -> bool:
    letters = sum(ch.isalpha() for ch in t)
    return letters / max(len(t), 1) > 0.55


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def shingles(text: str, k: int = 5) -> set[str]:
    w = text.lower().split()
    return {" ".join(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def near_duplicate(a: set[str], b: set[str], threshold: float = 0.85) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold
