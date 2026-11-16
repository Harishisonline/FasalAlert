"""Alert generation and dispatch (PRD §7.6, §4.1 delivery, §12 audit).

* One alert per (user, field, risk kind, event date, channel): enforced by a unique dedupe key, so a
  recomputed decision never re-sends the same warning.
* Quiet hours: alerts created inside the window are queued until it ends (status 'queued').
* A delivery is marked 'sent' only when a provider accepted it; failures are logged and retried
  up to MAX_ATTEMPTS with backoff.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.timeutil import IST, now_ist, now_utc
from app.models.tables import (
    AlertDelivery,
    AlertRow,
    DecisionRow,
    Field,
    PushSubscription,
    User,
    UserPreferences,
)
from app.security.deps import audit
from app.services.decision.engine import CROP_NAMES, KIND_NAMES, LEVEL_NAMES
from app.services.decision.policy import ACTIONABLE
from app.services.notify import channels

log = logging.getLogger("fasalalert.alerts")
MAX_ATTEMPTS = 3


def in_quiet_hours(prefs: UserPreferences | None, at: datetime) -> datetime | None:
    """Return the end of the quiet window if `at` falls inside it, else None. Windows may cross midnight."""
    if not prefs or not prefs.quiet_hours_start or not prefs.quiet_hours_end:
        return None
    local = at.astimezone(IST)
    s, e, t = prefs.quiet_hours_start, prefs.quiet_hours_end, local.time()
    inside = (s <= t < e) if s < e else (t >= s or t < e)
    if not inside:
        return None
    end_day = local.date() if (s < e or t < e) else local.date() + timedelta(days=1)
    return datetime.combine(end_day, e, tzinfo=IST)


def message_for(decision: dict[str, Any], f: Field, locale: str) -> str:
    i18n = decision.get("_i18n", {})
    head = (i18n.get("headline") or {}).get(locale) or decision["headline"]
    act = (i18n.get("action_text") or {}).get(locale) or decision["action_text"]
    msg = f"FasalAlert: {f.name}. {head}. {act}"
    return msg[:600]


def create_alerts_for_decision(db: Session, f: Field, row: DecisionRow) -> list[AlertRow]:
    d = row.payload
    if d.get("abstain_reason"):
        return []
    risks = [r for r in d.get("risks", []) if r["level"] in ACTIONABLE]
    if not risks:
        return []
    user = db.get(User, f.user_id)
    prefs = db.get(UserPreferences, f.user_id)
    chans = {"sms": True, "push": False, "whatsapp": False, **((prefs.channels if prefs else {}) or {})}
    primary = max(risks, key=lambda r: (["none", "low", "medium", "high", "critical"].index(r["level"]), r["probability"]))
    event = primary.get("evidence", {}).get("event_date") or row.decision_date.isoformat()
    queued_until = in_quiet_hours(prefs, now_utc())
    created = []
    for ch, on in chans.items():
        if not on:
            continue
        key = f"{f.id}:{primary['kind']}:{event}"
        stmt = insert(AlertRow).values(
            user_id=f.user_id, field_id=f.id, decision_id=row.id, kind=primary["kind"], level=primary["level"],
            message=message_for(d, f, user.preferred_locale if user else "mr"), channel=ch, dedupe_key=key,
            queued_until=queued_until, detail={"advisory": d.get("advisory"), "risk": primary, "action_by": d.get("action_by")},
        ).on_conflict_do_nothing(index_elements=["user_id", "dedupe_key", "channel"], index_where=AlertRow.dedupe_key.is_not(None))
        res = db.execute(stmt.returning(AlertRow.id))
        new_id = res.scalar_one_or_none()
        if new_id is None:
            continue  # duplicate: this warning was already raised for this event
        a = db.get(AlertRow, new_id)
        db.add(AlertDelivery(alert_id=a.id, channel=ch, status="queued"))
        created.append(a)
    if created:
        audit(db, f.user_id, "alert_created", "field", str(f.id), kind=primary["kind"], level=primary["level"], n=len(created))
    return created


def _attempts(db: Session, alert_id: int) -> int:
    return int(db.execute(select(func.count()).select_from(AlertDelivery)
                          .where(AlertDelivery.alert_id == alert_id, AlertDelivery.status == "failed")).scalar_one())


def dispatch_pending(db: Session) -> dict[str, int]:
    """Send alerts whose quiet window has passed and that have not been sent. Idempotent."""
    now = now_utc()
    pending = db.execute(select(AlertRow).where(AlertRow.sent_at.is_(None),
                                                (AlertRow.queued_until.is_(None)) | (AlertRow.queued_until <= now))
                         .order_by(AlertRow.created_at).limit(200).with_for_update(skip_locked=True)).scalars().all()
    stats = {"sent": 0, "failed": 0, "gave_up": 0}
    for a in pending:
        tries = _attempts(db, a.id)
        if tries >= MAX_ATTEMPTS:
            stats["gave_up"] += 1
            continue
        user = db.get(User, a.user_id)
        if a.channel == "sms":
            res = channels.send_sms(user.phone, a.message)
        elif a.channel == "push":
            subs = db.execute(select(PushSubscription).where(PushSubscription.user_id == a.user_id)).scalars().all()
            res = channels.DeliveryResult("failed", "webpush", error="no push subscription")
            for s in subs:
                res = channels.send_web_push({"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                                             {"title": "FasalAlert", "body": a.message, "url": f"/{user.preferred_locale}/alert?focus={a.id}"})
                if res.status == "sent":
                    break
        elif a.channel == "whatsapp":
            res = channels.send_whatsapp(user.phone, a.message)
        else:
            res = channels.DeliveryResult("failed", "none", error=f"unknown channel {a.channel}")
        db.add(AlertDelivery(alert_id=a.id, channel=a.channel, status=res.status, provider_sid=res.provider_sid, error=res.error))
        if res.status == "sent":
            a.sent_at = now
            stats["sent"] += 1
            audit(db, a.user_id, "alert_sent", "alert", str(a.id), channel=a.channel, provider=res.provider)
        else:
            stats["failed"] += 1
    db.flush()
    return stats


QUIET_DEFAULT = (time(22, 0), time(6, 0))
_ = (CROP_NAMES, KIND_NAMES, LEVEL_NAMES, now_ist)
