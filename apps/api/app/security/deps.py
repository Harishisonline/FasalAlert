"""Authentication dependencies, ownership checks and rate limiting."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError, not_found
from app.core.timeutil import ist_midnight
from app.models.tables import AuditLog, Field, User
from app.security.tokens import decode_access_token


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError("unauthenticated", "Sign in required")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    user = db.get(User, int(str(payload["sub"])))
    if user is None:
        raise ApiError("unauthenticated", "Sign in required")
    return user


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ApiError("forbidden", "You do not have access to this")
        return user

    return dep


def owned_field(db: Session, user: User, field_id: int) -> Field:
    """PRD §7.4: a field that belongs to someone else is a 404, never a 403."""
    field = db.get(Field, field_id)
    if field is None or field.user_id != user.id:
        raise not_found("Field")
    return field


class SlidingWindowLimiter:
    """In-process limiter for anonymous endpoints (PRD §12: public board 60/min per IP)."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise ApiError("rate_limited", "Too many requests", {"retry_after": int(self.window - (now - q[0])) + 1})
            q.append(now)


public_limiter = SlidingWindowLimiter(60, 60)


def public_rate_limit(request: Request) -> None:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    public_limiter.check(ip)


ASK_DAILY_LIMIT = 20


def asks_used_today(db: Session, user: User) -> int:
    start = ist_midnight()
    return int(
        db.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.user_id == user.id, AuditLog.action == "ask", AuditLog.created_at >= start
            )
        ).scalar_one()
    )


def audit(db: Session, user_id: int | None, action: str, entity: str, entity_id: str | None = None, **detail: object) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id, detail=detail))
