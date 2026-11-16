"""Phone OTP (PRD §7.2, §12): hashed storage, 5 attempts, 5-minute expiry, 3 sends per phone per hour,
60 s between sends. The OTP value is never logged."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.tables import OtpCode

OTP_TTL = timedelta(minutes=5)
RESEND_AFTER = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 3
MAX_ATTEMPTS = 5
_PHONE_RE = re.compile(r"^\+91[6-9]\d{9}$")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    digits = digits.lstrip("0") if len(digits) == 11 else digits
    phone = "+91" + digits
    if not _PHONE_RE.match(phone):
        raise ApiError("validation_error", "Enter a 10-digit mobile number", {"field": "phone"})
    return phone


def _hash(phone: str, code: str) -> str:
    return hmac.new(get_settings().otp_pepper.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def request_otp(db: Session, phone: str) -> tuple[str, int]:
    """Create an OTP. Returns (code, expires_in). Raises rate_limited with retry_after."""
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    sends = db.execute(
        select(func.count(), func.min(OtpCode.created_at), func.max(OtpCode.created_at)).where(
            OtpCode.phone == phone, OtpCode.created_at > hour_ago
        )
    ).one()
    count, oldest, latest = sends
    if count >= MAX_SENDS_PER_HOUR:
        retry = int((oldest + timedelta(hours=1) - now).total_seconds()) + 1
        raise ApiError("rate_limited", "Too many codes requested", {"retry_after": max(retry, 1)})
    if latest is not None and now - latest < RESEND_AFTER:
        retry = int((latest + RESEND_AFTER - now).total_seconds()) + 1
        raise ApiError("rate_limited", "Please wait before requesting a new code", {"retry_after": retry})
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(OtpCode(phone=phone, code_hash=_hash(phone, code), max_attempts=MAX_ATTEMPTS, expires_at=now + OTP_TTL))
    db.flush()
    return code, int(OTP_TTL.total_seconds())


def verify_otp(db: Session, phone: str, code: str) -> None:
    """Consume a valid OTP or raise. Attempts are counted against the latest unconsumed code."""
    if not re.fullmatch(r"\d{6}", code or ""):
        raise ApiError("validation_error", "Enter the 6-digit code", {"field": "code"})
    now = datetime.now(UTC)
    row = db.execute(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("validation_error", "Request a code first", {"field": "code", "reason": "no_code"})
    if row.attempts >= row.max_attempts:
        raise ApiError("forbidden", "Too many attempts", {"reason": "locked", "attempts_left": 0}, status=429)
    if row.expires_at <= now:
        raise ApiError("validation_error", "Code expired, request a new one", {"field": "code", "reason": "expired"})
    if not hmac.compare_digest(row.code_hash, _hash(phone, code)):
        row.attempts += 1
        db.commit()
        left = row.max_attempts - row.attempts
        if left <= 0:
            raise ApiError("forbidden", "Too many attempts", {"reason": "locked", "attempts_left": 0}, status=429)
        raise ApiError("validation_error", "Wrong code", {"field": "code", "reason": "wrong", "attempts_left": left})
    row.consumed_at = now
