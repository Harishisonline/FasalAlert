"""Assistant conversation history (docs/UX_QA_AUDIT.md ASK-08, ASK-09).

A question and its answer are saved together, after the answer is ready, into the user's thread. A
question the farmer stopped is never kept: Stop marks its request id here, a request that finishes after
that is not saved, and an answer already saved under that id is deleted with its question.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.timeutil import iso, now_utc
from app.models.tables import AskMessage, AskThread, User

TITLE_MAX = 60
CANCEL_TTL_S = 15 * 60
# Answer fields kept with a saved answer. asks_remaining and stt_available describe the moment, not the answer.
KEEP = ("answer", "cards", "sources", "abstain", "abstain_reason", "kvk", "intent", "answer_audio_url",
        "transcript", "low_confidence_terms", "asr_confidence")
NOT_A_QUESTION = {"stt_unavailable", "no_speech"}

_cancelled: dict[str, float] = {}
_lock = threading.Lock()


def mark_cancelled(request_id: str) -> None:
    now = time.monotonic()
    with _lock:
        for k in [k for k, t in _cancelled.items() if now - t > CANCEL_TTL_S]:
            del _cancelled[k]
        _cancelled[request_id] = now


def is_cancelled(request_id: str | None) -> bool:
    if not request_id:
        return False
    with _lock:
        return request_id in _cancelled


def make_title(question: str) -> str:
    """The first words of the first question (no model writes titles)."""
    text = re.sub(r"\s+", " ", question).strip()
    if len(text) <= TITLE_MAX:
        return text or "Question"
    cut = text[:TITLE_MAX]
    space = cut.rfind(" ")
    return (cut[:space] if space > TITLE_MAX // 2 else cut).rstrip(",.;: ") + "…"


def owned_thread(db: Session, user: User, thread_id: int) -> AskThread:
    """Another user's conversation is a 404, never a 403 (PRD §7.4)."""
    t = db.get(AskThread, thread_id)
    if t is None or t.user_id != user.id:
        raise not_found("Conversation")
    return t


def recent_turns(db: Session, thread: AskThread, limit: int = 8) -> list[dict[str, str]]:
    """The last turns of a conversation, oldest first, for the model to read follow-ups. Off-topic refusals are left
    out: they carry no facts, and a run of them would only teach the model to refuse again."""
    rows = db.execute(select(AskMessage).where(AskMessage.thread_id == thread.id).order_by(AskMessage.id.desc()).limit(limit * 2)).scalars().all()
    turns: list[dict[str, str]] = []
    for m in reversed(rows):
        if m.role == "assistant" and (m.payload or {}).get("abstain_reason") == "outside_domain":
            continue
        if m.content:
            turns.append({"role": m.role, "content": m.content})
    return turns[-limit:]


def message_out(m: AskMessage) -> dict[str, Any]:
    p = m.payload or {}
    return {"id": m.id, "role": m.role, "content": m.content, "created_at": iso(m.created_at),
            "field_id": p.get("field_id"), "spoken": bool(p.get("spoken")),
            "response": {k: p.get(k) for k in KEEP} if m.role == "assistant" else None}


def summary_out(db: Session, t: AskThread) -> dict[str, Any]:
    count, = db.execute(select(func.count()).select_from(AskMessage).where(AskMessage.thread_id == t.id)).one()
    last = db.execute(select(AskMessage.content).where(AskMessage.thread_id == t.id, AskMessage.role == "assistant")
                      .order_by(AskMessage.id.desc()).limit(1)).scalar_one_or_none()
    snippet = re.sub(r"\s+", " ", last or "").strip()
    return {"id": t.id, "title": t.title, "pinned": t.pinned, "field_id": t.field_id, "created_at": iso(t.created_at),
            "last_activity_at": iso(t.last_activity_at), "message_count": int(count),
            "snippet": snippet[:160] + ("…" if len(snippet) > 160 else "")}


def record(db: Session, user: User, thread: AskThread | None, *, question_text: str | None, spoken: bool,
           field_id: int | None, request_id: str | None, result: dict[str, Any]) -> dict[str, Any]:
    """Save the exchange and add the thread and message ids to the response (ADDITIVE fields)."""
    question = (result.get("transcript") or question_text or "").strip()
    base = {**result, "thread_id": thread.id if thread else None, "thread_title": thread.title if thread else None,
            "user_message": None, "assistant_message": None, "cancelled": False}
    if result.get("intent") in NOT_A_QUESTION or not question:
        return base
    if is_cancelled(request_id):
        return {**base, "cancelled": True}
    if thread is None:
        thread = AskThread(user_id=user.id, title=make_title(question), field_id=field_id)
        db.add(thread)
        db.flush()
    um = AskMessage(thread_id=thread.id, role="user", content=question, request_id=request_id,
                    payload={"field_id": field_id, "spoken": spoken})
    am = AskMessage(thread_id=thread.id, role="assistant", content=result.get("answer") or "", request_id=request_id,
                    payload={"field_id": field_id, **{k: result.get(k) for k in KEEP}})
    db.add_all([um, am])
    thread.last_activity_at = now_utc()
    if field_id is not None:
        thread.field_id = field_id
    db.flush()
    db.refresh(um)
    db.refresh(am)
    return {**base, "thread_id": thread.id, "thread_title": thread.title,
            "user_message": message_out(um), "assistant_message": message_out(am)}


def cancel(db: Session, user: User, request_id: str) -> bool:
    """Stop: forget the question whether or not its answer was already saved. True when rows were removed."""
    mark_cancelled(request_id)
    threads = db.execute(select(AskMessage.thread_id).join(AskThread, AskThread.id == AskMessage.thread_id)
                         .where(AskMessage.request_id == request_id, AskThread.user_id == user.id).distinct()).scalars().all()
    if not threads:
        return False
    db.execute(delete(AskMessage).where(AskMessage.request_id == request_id, AskMessage.thread_id.in_(threads)))
    for tid in threads:
        left, = db.execute(select(func.count()).select_from(AskMessage).where(AskMessage.thread_id == tid)).one()
        if left == 0:
            db.execute(delete(AskThread).where(AskThread.id == tid))
    return True
