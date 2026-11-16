"""Ask, alerts, FPO and health endpoints (PRD §7.5, §7.6, §5, §11)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import ApiError, not_found
from app.core.timeutil import iso, now_utc
from app.models.tables import (
    AlertDelivery,
    AlertRow,
    Field,
    Fpo,
    FpoMember,
    FpoPost,
    IngestRun,
    ModelRegistry,
    User,
)
from app.schemas.bodies import AskBody, FeedbackBody, FpoPostBody
from app.security.deps import audit, current_user
from app.services import assistant, conversations
from app.services.foundry import imd
from app.services.notify.channels import availability
from app.services.voice import speech

router = APIRouter()


# ---------- ask ----------
@router.post("/ask", tags=["ask"])
def ask(body: AskBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if not body.text and not body.audio_b64:
        raise ApiError("validation_error", "Send text or audio", {"field": "text"})
    thread = conversations.owned_thread(db, user, body.thread_id) if body.thread_id is not None else None
    # Earlier turns let the assistant follow up ("I mean my G spot field").
    history = conversations.recent_turns(db, thread) if thread is not None else None
    result = assistant.ask(db, user, body.text, body.audio_b64, body.field_id, body.locale, history=history)
    # ADDITIVE: the exchange is saved to the conversation (a new one when thread_id is absent).
    return conversations.record(db, user, thread, question_text=body.text, spoken=bool(body.audio_b64),
                                field_id=body.field_id, request_id=body.request_id, result=result)


@router.get("/ask/audio/{audio_id}", tags=["ask"], summary="ADDITIVE: spoken answer audio (WAV)")
def ask_audio(audio_id: str, user: User = Depends(current_user)) -> FileResponse:
    # signed-in users only (the web app fetches it through its BFF proxy); the id is a random 128-bit hex string
    p = speech.audio_path(audio_id)
    if p is None:
        raise not_found("Audio")
    return FileResponse(p, media_type="audio/wav")


# ---------- alerts ----------
def _alert(db: Session, a: AlertRow) -> dict[str, Any]:
    dels = db.execute(select(AlertDelivery).where(AlertDelivery.alert_id == a.id).order_by(AlertDelivery.created_at)).scalars().all()
    f = db.get(Field, a.field_id) if a.field_id else None
    return {"id": a.id, "field_id": a.field_id, "field_name": f.name if f else None, "decision_id": a.decision_id,
            "kind": a.kind, "level": a.level, "message": a.message, "channel": a.channel, "sent_at": iso(a.sent_at),
            "read_at": iso(a.read_at), "feedback": a.feedback, "created_at": iso(a.created_at),
            "deliveries": [{"channel": d.channel, "status": d.status, "created_at": iso(d.created_at),
                            "provider": d.provider_sid if d.provider_sid in ("dev-outbox",) else None, "error": d.error} for d in dels],
            "queued_until": iso(a.queued_until), "detail": a.detail or None}


@router.get("/alerts", tags=["alerts"])
def list_alerts(kind: str | None = Query(default=None), status: str | None = Query(default=None, pattern="^(read|unread)$"),
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(AlertRow).where(AlertRow.user_id == user.id)
    if kind:
        q = q.where(AlertRow.kind == kind)
    if status == "read":
        q = q.where(AlertRow.read_at.is_not(None))
    elif status == "unread":
        q = q.where(AlertRow.read_at.is_(None))
    rows = db.execute(q.order_by(AlertRow.created_at.desc()).limit(200)).scalars().all()
    unread = db.execute(select(func.count()).select_from(AlertRow).where(AlertRow.user_id == user.id, AlertRow.read_at.is_(None))).scalar_one()
    return {"alerts": [_alert(db, a) for a in rows], "unread": int(unread)}


def _own_alert(db: Session, user: User, alert_id: int) -> AlertRow:
    a = db.get(AlertRow, alert_id)
    if a is None or a.user_id != user.id:
        raise not_found("Alert")
    return a


@router.post("/alerts/{alert_id}/read", tags=["alerts"])
def read_alert(alert_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _own_alert(db, user, alert_id)
    if a.read_at is None:
        a.read_at = now_utc()
        db.add(AlertDelivery(alert_id=a.id, channel=a.channel, status="read"))
        audit(db, user.id, "alert_read", "alert", str(a.id))
    db.flush()
    return _alert(db, a)


@router.post("/alerts/{alert_id}/feedback", tags=["alerts"])
def alert_feedback(alert_id: int, body: FeedbackBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _own_alert(db, user, alert_id)
    a.feedback = body.value
    audit(db, user.id, "alert_feedback", "alert", str(a.id), value=body.value)
    db.flush()
    return _alert(db, a)


# ---------- FPO ----------
def _membership(db: Session, user: User) -> FpoMember | None:
    return db.execute(select(FpoMember).where(FpoMember.user_id == user.id)).scalars().first()


@router.get("/fpo/me", tags=["fpo"])
def fpo_me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    m = _membership(db, user)
    if m is None:
        raise not_found("FPO membership")
    fpo = db.get(Fpo, m.fpo_id)
    count = db.execute(select(func.count()).select_from(FpoMember).where(FpoMember.fpo_id == m.fpo_id)).scalar_one()
    return {"id": fpo.id, "name": fpo.name, "district_id": fpo.district_id, "member_count": int(count), "my_role": m.role}


def _require_member(db: Session, user: User, fpo_id: int) -> FpoMember:
    m = db.execute(select(FpoMember).where(FpoMember.user_id == user.id, FpoMember.fpo_id == fpo_id)).scalar_one_or_none()
    if m is None and user.role != "admin":
        raise not_found("FPO")
    return m  # type: ignore[return-value]


@router.get("/fpo/{fpo_id}/posts", tags=["fpo"])
def fpo_posts(fpo_id: int, kind: str | None = Query(default=None), user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _require_member(db, user, fpo_id)
    q = select(FpoPost, User.name).join(User, User.id == FpoPost.author_id, isouter=True).where(FpoPost.fpo_id == fpo_id, FpoPost.deleted_at.is_(None))
    if kind:
        q = q.where(FpoPost.kind == kind)
    rows = db.execute(q.order_by(FpoPost.pinned.desc(), FpoPost.created_at.desc()).limit(100)).all()
    # PRD §12: the feed shows display names only, never phone numbers.
    return [{"id": p.id, "kind": p.kind, "title": p.title, "body_md": p.body_md, "locale": p.locale, "pinned": p.pinned,
             "author_name": name, "created_at": iso(p.created_at)} for p, name in rows]


@router.post("/fpo/{fpo_id}/posts", tags=["fpo"], status_code=201)
def fpo_create_post(fpo_id: int, body: FpoPostBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    m = _require_member(db, user, fpo_id)
    pinned = bool(body.pinned)
    if pinned and not (user.role in ("fpo_manager", "admin") or (m and m.role == "manager")):
        raise ApiError("forbidden", "Only FPO managers can pin a broadcast")  # PRD §5
    p = FpoPost(fpo_id=fpo_id, author_id=user.id, kind=body.kind, title=body.title, body_md=body.body_md, locale=body.locale, pinned=pinned)
    db.add(p)
    db.flush()
    audit(db, user.id, "fpo_post", "fpo_post", str(p.id))
    return {"id": p.id, "kind": p.kind, "title": p.title, "body_md": p.body_md, "locale": p.locale, "pinned": p.pinned,
            "author_name": user.name, "created_at": iso(p.created_at)}


# ---------- health ----------
@router.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    models = []
    for r in db.execute(select(ModelRegistry).order_by(ModelRegistry.name, ModelRegistry.trained_at.desc())).scalars():
        models.append({"name": r.name, "version": r.version, "trained_at": iso(r.trained_at),
                       "status": (r.metrics or {}).get("serving_status", "serving")})
    fresh = []
    for source, ttl in (("open-meteo-forecast", timedelta(hours=3, minutes=15)), ("agmarknet", timedelta(hours=30)),
                        ("open-meteo-archive", timedelta(days=2)), ("advisory-corpus", None)):
        last = db.execute(select(func.max(IngestRun.finished_at)).where(IngestRun.source == source, IngestRun.status == "ok")).scalar_one()
        fresh.append({"source": source, "last_fetched_at": iso(last),
                      "stale": last is None or (ttl is not None and now_utc() - last > ttl)})
    s = get_settings()
    av = availability()
    integrations = {"imd_api": imd.status(), "data_gov_in": "configured" if s.data_gov_in_api_key else "not_configured",
                    "bhashini": "configured" if speech.bhashini_configured() else "not_configured",
                    "whisper": "configured" if speech.whisper_configured() else "not_configured",
                    "sms": "configured" if av["sms"] else "not_configured", "web_push": "configured" if av["push"] else "not_configured",
                    "whatsapp": "configured" if av["whatsapp"] else "not_configured"}
    degraded = any(f["stale"] for f in fresh[:1]) or not models
    return {"status": "degraded" if degraded else "ok", "models": models, "data_freshness": fresh, "integrations": integrations}
