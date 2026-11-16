"""Deterministic grounded answer composition (PRD §9.4 grounding rule, §12 hallucinated numbers).

No generative model is used. An answer is assembled from:
  1. template sentences in the user's language that state model outputs (numbers come only from
     structured model output passed in `facts`), and
  2. verbatim sentences quoted from verified advisory chunks, each with its citation.
A post-composition validator checks that every number in the answer appears in the supplied context.
If a check fails, or the evidence is insufficient or conflicting, the composer abstains.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.rag.retrieve import Hit
from app.services.rag.text import sentences
from app.services.rag.vocab import STOPWORDS, expand_query

NUM = re.compile(r"(?<![\w.])[-−]?\d+(?:[.,]\d+)*")
DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
DOSE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|percent|per cent|ml|mL|g\b|gm|gram|kg|ppm|l\b|litre|liter|lit\b|मिली|मि\.ली|ग्रॅम|ग्राम|किलो|लिटर|टक्के|प्रतिशत)", re.I)
ADVICE = re.compile(r"\b(irrigat\w*|apply|spray|cover|use|avoid|should|recommend\w*|protect\w*|remove|harvest|keep|provide|maintain|"
                    r"drain|mulch|prune|install)\b|करावी|करावे|द्यावे|टाळा|फवारणी|करें|दें|बचें", re.I)
NOISE = re.compile(r"\(\w[^)]*\d{4}\)|\bfigure\b|\btable\b|\bet al\b|\bpage\b|\breaders\b|\breferred to\b|\badditional resources\b", re.I)
# A running header or footer glued into a sentence at a page break: three or more all-caps words in a row,
# or a page number beside a bracket ("20 ]FROST PROTECTION: ...[").
# A list marker glued to the end of a heading ("... Input arrangements 1.", "... fruit harvest B.") marks a heading
# or caption, not a sentence of advice.
PAGE_FURNITURE = re.compile(r"\b[A-Z][A-Z:,]{2,}(?:\s+[A-Z][A-Z:,]{2,}){2,}|\d+\s*\][A-Z]|[A-Z]\[|\s(?:\d{1,2}|[A-Z])\.$")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
NEGATION = re.compile(r"\b(do not|don't|avoid|never|should not)\b|नये|टाळा|न करें|मत", re.IGNORECASE)


@dataclass
class Fact:
    label: str
    value: str                    # already formatted with unit, e.g. "3.2 °C"
    source: dict[str, Any]        # SourceRef dict


@dataclass
class Composition:
    answer: str
    cards: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    abstain: bool
    abstain_reason: str | None = None
    quotes: list[dict[str, Any]] = field(default_factory=list)


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").replace("−", "-") for n in NUM.findall(text.translate(DEVA_DIGITS))}


def validate_numbers(answer: str, context: list[str]) -> bool:
    """Every number in the answer must appear somewhere in the supplied context (PRD AC 11)."""
    ctx: set[str] = set()
    for c in context:
        ctx |= numbers(c)
    return numbers(answer) <= ctx


STOP = STOPWORDS


def best_sentences(hit: Hit, query: str, max_n: int = 2, crop: str | None = None) -> list[str]:
    """Sentences that share a topic word with the question. A sentence matching only the crop name is not
    evidence (it would answer a different question), so it is never picked. Actionable advice ranks above
    background text. A sentence with a dose is quoted only from a source written for the same crop: a dose
    is never carried over from a general document or another crop."""
    from app.services.rag.vocab import crop_terms

    crops = crop_terms()
    q_terms = {w.strip("?,.!") for w in expand_query(query).lower().split() if len(w) > 3}
    q_terms = {w for w in q_terms if w and w not in STOP and w not in crops}
    scored = []
    for s in sentences(hit.content):
        if len(s.split()) < 6 or len(s) > 400:
            continue
        low = s.lower()
        overlap = sum(1 for w in q_terms if w in low)
        if not overlap:
            continue
        if DOSE.search(s) and (crop is None or hit.crop != crop):
            continue
        if NOISE.search(s) or PAGE_FURNITURE.search(s):   # citations, captions, running headers: never quoted as advice
            continue
        if hit.page is not None and DEVANAGARI.search(s):
            # Devanagari extracted from a PDF: legacy font encodings garble it (पिकात -> पपकात, मिली -> न्मली), and a
            # garbled dose is unsafe to show. Searchable, never quoted, until a reviewed Unicode source exists.
            continue
        score = overlap + (2 if ADVICE.search(s) else 0)
        if score > 0:
            scored.append((score, -len(s), s))
    scored.sort(reverse=True)
    return [s for _, _, s in scored[:max_n]]


def conflicting(hits: list[Hit], query: str) -> bool:
    """Crude conflict check: two top passages from different documents, one telling the farmer to do an
    action named in the question and the other telling them not to. Conflict leads to abstention."""
    if len(hits) < 2:
        return False
    a, b = hits[0], hits[1]
    if a.doc_id == b.doc_id:
        return False
    sa, sb = " ".join(best_sentences(a, query)), " ".join(best_sentences(b, query))
    return bool(NEGATION.search(sa)) != bool(NEGATION.search(sb)) and _shared_verb(sa, sb)


def _shared_verb(a: str, b: str) -> bool:
    verbs = {"irrigat", "spray", "harvest", "prun", "cover", "apply", "sow", "transport", "store"}
    return any(v in a.lower() and v in b.lower() for v in verbs)


def source_of(hit: Hit) -> dict[str, Any]:
    return {"label": f"{hit.institution}: {hit.title}" + (f" ({hit.year})" if hit.year else ""),
            "url": hit.source_url, "fetched_at": None, "kind": "advisory"}


LEAD = {
    "en": "From verified advice",
    "mr": "खात्रीशीर सल्ल्यानुसार",
    "hi": "प्रमाणित सलाह के अनुसार",
}
SOURCE_LANG_NOTE = {"mr": " (मूळ स्रोत इंग्रजीत)", "hi": " (मूल स्रोत अंग्रेज़ी में)", "en": ""}


def compose(
    query: str, locale: str, facts: list[Fact], hits: list[Hit], intro: str | None = None,
    require_advice: bool = True, template_constants: list[str] | None = None, crop: str | None = None,
) -> Composition:
    """`intro` is a template sentence already filled with fact values (so it only contains fact numbers)."""
    sources: list[dict[str, Any]] = []
    for f in facts:   # several facts share one source; list it once
        if f.source not in sources:
            sources.append(f.source)
    cards = [{"label": f.label, "value": f.value, "source": f.source} for f in facts]
    if require_advice and not hits:
        return Composition("", cards, sources, True, "no_retrieval_above_threshold")
    if hits and conflicting(hits, query):
        return Composition("", cards, sources, True, "no_retrieval_above_threshold")
    parts = [intro] if intro else []
    quotes = []
    for h in hits[:3]:
        if len(quotes) == 2:
            break
        if crop and h.crop not in (crop, None):
            continue
        sents = best_sentences(h, query, crop=crop)
        if not sents:
            continue
        quote = " ".join(sents)
        note = SOURCE_LANG_NOTE.get(locale, "") if h.lang != locale else ""
        parts.append(f"{LEAD.get(locale, LEAD['en'])} ({h.institution}{note}): “{quote}”")
        quotes.append({"doc_id": h.doc_id, "chunk_id": h.id, "text": quote, "similarity": round(h.similarity, 3),
                       "page": h.page})
        if source_of(h) not in sources:
            sources.append(source_of(h))
    if require_advice and not quotes:
        return Composition("", cards, sources, True, "no_retrieval_above_threshold")
    answer = " ".join(p for p in parts if p)
    # The intro is checked, never trusted: its numbers must come from model facts or retrieved passages.
    context = [f.value for f in facts] + [f.label for f in facts] + [h.content for h in hits] + (template_constants or [])
    if not answer or not validate_numbers(answer, context):
        return Composition("", cards, sources, True, "no_retrieval_above_threshold")
    return Composition(answer, cards, sources, False, None, quotes)
