"""JWT access tokens (15 min) and rotating, hashed, revocable refresh tokens (PRD §12)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.tables import RefreshToken, User

ALGO = "HS256"


def _now() -> datetime:
    return datetime.now(UTC)


def issue_access_token(user: User) -> str:
    s = get_settings()
    now = _now()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "loc": user.preferred_locale,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=s.access_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def decode_access_token(token: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    except jwt.ExpiredSignatureError as e:
        raise ApiError("unauthenticated", "Access token expired") from e
    except jwt.PyJWTError as e:
        raise ApiError("unauthenticated", "Invalid access token") from e
    if payload.get("typ") != "access":
        raise ApiError("unauthenticated", "Invalid access token")
    return payload


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(db: Session, user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash(token),
            expires_at=_now() + timedelta(days=get_settings().refresh_token_ttl_days),
        )
    )
    db.flush()
    return token


def rotate_refresh_token(db: Session, token: str) -> tuple[User, str]:
    """Revoke the presented token and issue a new one. Reuse of a revoked token revokes the whole family."""
    row = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(token)).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("unauthenticated", "Invalid refresh token")
    if row.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        db.commit()
        raise ApiError("unauthenticated", "Refresh token reuse detected; please sign in again")
    if row.expires_at <= _now():
        raise ApiError("unauthenticated", "Refresh token expired")
    row.revoked_at = _now()
    user = db.get(User, row.user_id)
    if user is None:
        raise ApiError("unauthenticated", "Invalid refresh token")
    return user, issue_refresh_token(db, user.id)


def revoke_refresh_token(db: Session, token: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash(token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
