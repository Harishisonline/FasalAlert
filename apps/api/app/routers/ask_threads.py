"""ADDITIVE: assistant conversation history and Stop (docs/UX_QA_AUDIT.md ASK-08, ASK-09)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError
from app.models.tables import AskMessage, AskThread, User
from app.schemas.bodies import CancelAskBody, ThreadPatchBody
from app.security.deps import current_user
from app.services import conversations as conv

router = APIRouter()


@router.get("/ask/threads", tags=["ask"], summary="ADDITIVE: the user's conversations, most recent first")
def list_threads(q: str | None = Query(default=None, max_length=80), limit: int = Query(30, ge=1, le=100),
                 cursor: str | None = Query(default=None, max_length=80),
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(AskThread).where(AskThread.user_id == user.id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        in_messages = select(AskMessage.id).where(AskMessage.thread_id == AskThread.id, AskMessage.content.ilike(like)).exists()
        stmt = stmt.where(or_(AskThread.title.ilike(like), in_messages))
    if cursor:
        try:
            at, tid = cursor.rsplit("|", 1)
            stmt = stmt.where(tuple_(AskThread.last_activity_at, AskThread.id) < tuple_(datetime.fromisoformat(at), int(tid)))
        except ValueError as e:
            raise ApiError("validation_error", "Bad cursor", {"field": "cursor"}) from e
    rows = db.execute(stmt.order_by(AskThread.last_activity_at.desc(), AskThread.id.desc()).limit(limit + 1)).scalars().all()
    page = rows[:limit]
    nxt = f"{page[-1].last_activity_at.isoformat()}|{page[-1].id}" if len(rows) > limit and page else None
    return {"items": [conv.summary_out(db, t) for t in page], "next_cursor": nxt}


@router.get("/ask/threads/{thread_id}", tags=["ask"], summary="ADDITIVE: one conversation with its messages")
def get_thread(thread_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = conv.owned_thread(db, user, thread_id)
    msgs = db.execute(select(AskMessage).where(AskMessage.thread_id == t.id).order_by(AskMessage.id)).scalars().all()
    return {**conv.summary_out(db, t), "messages": [conv.message_out(m) for m in msgs]}


@router.patch("/ask/threads/{thread_id}", tags=["ask"], summary="ADDITIVE: rename or save (pin) a conversation")
def patch_thread(thread_id: int, body: ThreadPatchBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = conv.owned_thread(db, user, thread_id)
    if body.title is not None:
        title = " ".join(body.title.split())
        if not title:
            raise ApiError("validation_error", "Give the conversation a name", {"field": "title"})
        t.title = title
    if body.pinned is not None:
        t.pinned = body.pinned
    db.flush()
    return conv.summary_out(db, t)


@router.delete("/ask/threads/{thread_id}", tags=["ask"], status_code=204, summary="ADDITIVE: delete a conversation")
def delete_thread(thread_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    db.delete(conv.owned_thread(db, user, thread_id))   # its messages cascade in the database
    return Response(status_code=204)


@router.post("/ask/cancel", tags=["ask"], summary="ADDITIVE: Stop. The question with this request id is not kept")
def cancel_ask(body: CancelAskBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"removed": conv.cancel(db, user, body.request_id)}
