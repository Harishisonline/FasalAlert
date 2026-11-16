"""Build grounded Ask context from the user's fields, decisions and RAG hits, then draft via Groq."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import Field, User
from app.services.llm.farmer import farmer_context
from app.services.llm.groq import chat_completion
from app.services.rag.compose import Fact, numbers
from app.services.rag.retrieve import Hit
from app.services.voice.intents import Intent

log = logging.getLogger("fasalalert.llm")
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINK_LEGACY_RE = re.compile(r"<thinking>[\s\S]*?</thinking>", re.IGNORECASE)

OUTSIDE = "OUTSIDE_DOMAIN"

SYSTEM = f"""You are FasalAlert, the farming assistant of one farmer in Maharashtra. CONTEXT is everything FasalAlert
stores about this farmer: their account (name, language, units), every field they added (name, crop, variety, place,
season start date, area, crop stage, calibration, the latest decision with its risks), the selected field's forecast,
market and road to the mandi, their recent alerts, their KVK, and verified advisory passages. Earlier turns of this
conversation come before the question.

Rules:
1. In scope: anything about this farmer's account, fields and crops, and farming in general: weather, crop stage and
   health, irrigation, pests and disease, spraying, harvest, mandi prices, roads to market, alerts, and how to use
   FasalAlert. "What am I growing", "tell me about my field", "what is my name", "where is my farm", "help me" are in
   scope: answer them from CONTEXT, for this farmer, by name of the field.
2. Only when the question has nothing to do with farming or with this farmer, reply with exactly {OUTSIDE} and nothing else.
3. Use only facts in CONTEXT and the earlier turns. Never invent temperatures, dates, prices, doses, chances or places.
4. Every number you write must appear exactly as written in CONTEXT: copy it, do not round, convert or compute new numbers.
5. When the farmer names no field, answer for the field with "selected": true; when they name another field, use that one.
6. Say plainly when something is unavailable (for example a risk that could not be checked today) instead of guessing,
   and suggest calling the KVK in CONTEXT when they need advice you do not have.
7. Advice on what to do must come from the decision, the advisory or the advisory passages in CONTEXT; name the
   institution when you use a passage.
8. Answer the question that was asked. A rain question gets rain, a frost question gets frost, a pest question gets
   pests: do not add other risks, temperatures or prices unless asked. A general "help" may summarise the field.
9. Short sentences a farmer can act on, spoken style, no markdown, no headings, no lists of more than 4 items.
10. Reply in the farmer's language given as Locale (en English, mr Marathi, hi Hindi).
"""


def _field_rows(db: Session, user: User) -> list[dict[str, Any]]:
    """Fallback when the full farmer context cannot be built: the fields as saved."""
    rows = db.execute(select(Field).where(Field.user_id == user.id).order_by(Field.id)).scalars().all()
    return [{"id": f.id, "name": f.name, "crop": f.crop, "variety": f.variety,
             "season_start_date": f.sowing_date.isoformat() if f.sowing_date else None, "area_sqm": f.area_sqm} for f in rows]


def build_context(
    *,
    db: Session,
    user: User,
    question: str,
    locale: str,
    intent: Intent,
    field: Field | None,
    decision: dict[str, Any] | None,
    facts: list[Fact],
    hits: list[Hit],
    intro: str | None,
    kvk: dict[str, str] | None,
) -> str:
    try:
        farmer = farmer_context(db, user, field, locale)
    except Exception:  # noqa: BLE001 - the answer degrades to the facts below, never to invented data
        log.exception("farmer context unavailable")
        farmer = {"fields": _field_rows(db, user)}
    payload: dict[str, Any] = {
        "locale": locale,
        "question": question,
        "intent": intent.name,
        "named_crop": intent.crop,
        **farmer,
        "selected_field": None,
        "today_decision": None,
        "model_facts": [{"label": f.label, "value": f.value, "source": f.source.get("label")} for f in facts],
        "template_intro": intro,
        "rag_passages": [],
        "kvk": kvk or farmer.get("kvk"),
    }
    if field is not None:
        payload["selected_field"] = {"id": field.id, "name": field.name, "crop": field.crop}
    if decision:
        # Keep the structured decision but drop huge nested blobs if any.
        payload["today_decision"] = {
            "primary_action": decision.get("primary_action"),
            "deadline": decision.get("deadline"),
            "abstain_reason": decision.get("abstain_reason"),
            "risks": decision.get("risks", [])[:6],
            "checks": decision.get("checks"),
            "sources": decision.get("sources", [])[:6],
        }
    for h in hits[:3]:
        payload["rag_passages"].append({
            "institution": h.institution,
            "title": h.title,
            "year": h.year,
            "crop": h.crop,
            "stage": h.stage,
            "page": h.page,
            "similarity": round(h.similarity, 3),
            "excerpt": h.content[:700],
            "source_url": h.source_url,
        })
    return json.dumps(payload, ensure_ascii=False, default=str)


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = _THINK_RE.sub("", text)
    text = _THINK_LEGACY_RE.sub("", text).strip()
    return text or None


def draft_answer(context_json: str, locale: str, question: str, allowed_numbers: set[str],
                 history: list[dict[str, str]] | None = None) -> str | None:
    """The model's answer, `OUTSIDE` when it judges the question off-topic, or None (no key, an error, or numbers
    that are not in CONTEXT even after one correction)."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    for turn in (history or [])[-8:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"][:800]})
    messages.append({
        "role": "user",
        "content": (
            f"Locale: {locale}\n"
            f"Farmer question: {question}\n\n"
            f"CONTEXT (JSON):\n{context_json}\n\n"
            "Write the final answer only. No preamble."
        ),
    })
    text = _clean(chat_completion(messages))
    if not text:
        return None
    if text.strip().strip(".").upper() == OUTSIDE:
        return OUTSIDE
    # Keep the PRD number rule: every number in the answer must already be in context/facts (compared by value,
    # so "4 hectares" matches 4.0 in CONTEXT).
    ctx = [context_json, *allowed_numbers, *(t.get("content", "") for t in (history or []))]
    known = _values(ctx)
    if not _ungrounded(text, known):
        return text
    bad = _ungrounded(text, known)
    log.info("groq answer had numbers outside CONTEXT; asking once for a correction")
    retry = [*messages, {"role": "assistant", "content": text},
             {"role": "user", "content": f"These numbers are not in CONTEXT: {', '.join(bad[:12])}. Rewrite the answer using only "
                                         "numbers copied exactly from CONTEXT, or leave the number out."}]
    text = _clean(chat_completion(retry))
    if text and text.strip().strip(".").upper() != OUTSIDE and not _ungrounded(text, known):
        return text
    log.info("groq answer dropped: numbers not in CONTEXT %s", bad[:12])
    return None


def _value(n: str) -> float | None:
    try:
        return round(float(n), 4)
    except ValueError:
        return None


def _values(blobs: list[str]) -> set[float | str]:
    out: set[float | str] = set()
    for b in blobs:
        for n in numbers(b):
            v = _value(n)
            out.add(v if v is not None else n)
    return out


def _ungrounded(text: str, known: set[float | str]) -> list[str]:
    return sorted(n for n in numbers(text) if (_value(n) if _value(n) is not None else n) not in known)


def allowed_number_tokens(facts: list[Fact], intro: str | None, hits: list[Hit], extras: list[str] | None = None) -> set[str]:
    blobs = [f.value for f in facts] + [f.label for f in facts] + ([intro] if intro else []) + [h.content for h in hits]
    blobs += extras or []
    out: set[str] = set()
    for b in blobs:
        out |= numbers(b)
    return out
