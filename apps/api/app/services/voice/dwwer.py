"""Domain-weighted word error rate (PRD §9.5, AC 13 and 14).

Each reference token gets a weight from the severity table in data/terms_mr.json: crop, pest, disease,
chemical, stage and numeric quantities weigh 20; place names 3; fillers 1; other words 1.
DW-WER = (sum of weights of substituted + deleted reference tokens + weights of inserted hypothesis
tokens) / (sum of weights of all reference tokens). Plain WER is the same with every weight = 1.
Multi-word terms ("copper oxychloride") are matched before tokenisation and treated as one token.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.services.rag.vocab import terms

_PUNCT = re.compile(r"[^\wऀ-ॿ%°.]+", re.UNICODE)
_NUMERIC = re.compile(r"^[-−]?[\d०-९]+([.,][\d०-९]+)?%?$")


def _phrases() -> list[tuple[str, str]]:
    out = []
    for cat, entries in terms()["categories"].items():
        for e in entries:
            for a in [e["canonical"], *e.get("aliases", [])]:
                if " " in a.strip():
                    out.append((a.lower(), cat))
    return sorted(out, key=lambda x: -len(x[0]))


def tokenize(text: str) -> list[str]:
    t = unicodedata.normalize("NFC", text.lower())
    for phrase, _ in _phrases():
        t = t.replace(phrase, phrase.replace(" ", "_"))
    return [w for w in _PUNCT.sub(" ", t).split() if w]


def category(token: str) -> str:
    from app.services.rag.vocab import alias_index

    word = token.replace("_", " ")
    if _NUMERIC.match(word):
        return "quantity"
    numw = {w for ws in terms().get("number_words", {}).values() for w in ws}
    if word in numw:
        return "quantity"
    hit = alias_index().get(word)
    if not hit:
        for cand in marathi_stems(word):
            hit = alias_index().get(cand)
            if hit:
                break
    if hit:
        cat = hit[1]
        return cat if cat in terms()["weights"] else "other"
    return "other"


# Common Marathi and Hindi postpositions and case endings, longest first.
_SUFFIXES = ("मध्ये", "पासून", "साठी", "च्या", "वरील", "वर", "ला", "चा", "ची", "चे", "ने", "नी", "ना", "त", "ं", "में", "से", "का", "की", "के", "को", "पर")


def marathi_stems(word: str) -> list[str]:
    """Candidate dictionary forms of an inflected Devanagari word (आंब्यावर -> आंब्या -> आंबा)."""
    if not any("\u0900" <= ch <= "\u097f" for ch in word):
        return []
    cands = []
    stems = [word] + [word[: -len(sfx)] for sfx in _SUFFIXES if word.endswith(sfx) and len(word) - len(sfx) >= 2]
    for st in stems:
        cands.append(st)
        if st.endswith("्या"):
            cands.append(st[:-3] + "ा")      # oblique -या back to -ा (आंब्या -> आंबा)
        if st.endswith("ी"):
            cands.append(st[:-1])
        if st.endswith("े"):
            cands.append(st[:-1] + "ा")
        if st.endswith("ा"):
            cands.append(st[:-1])
    return cands[1:] if cands and cands[0] == word else cands


def weight(token: str) -> int:
    return int(terms()["weights"].get(category(token), 1))


@dataclass
class Score:
    wer: float
    dw_wer: float
    ref_tokens: int
    errors: int
    weighted_errors: float
    weighted_ref: float
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)


def score(reference: str, hypothesis: str) -> Score:
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    n, m = len(ref), len(hyp)
    # Levenshtein alignment with backtrace
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j = n, m
    errors, werr = 0, 0.0
    by_cat: dict[str, dict[str, int]] = {}

    def bump(cat: str, key: str) -> None:
        by_cat.setdefault(cat, {"ref": 0, "errors": 0})[key] += 1

    for tok in ref:
        bump(category(tok), "ref")
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                errors += 1
                werr += weight(ref[i - 1])
                bump(category(ref[i - 1]), "errors")
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            errors += 1
            werr += weight(ref[i - 1])
            bump(category(ref[i - 1]), "errors")
            i -= 1
        else:
            errors += 1
            werr += weight(hyp[j - 1])
            by_cat.setdefault(category(hyp[j - 1]), {"ref": 0, "errors": 0})["errors"] += 1
            j -= 1
    wref = float(sum(weight(t) for t in ref)) or 1.0
    return Score(errors / max(n, 1), werr / wref, n, errors, werr, wref, by_cat)
