"""Auth (PRD §7.2, §12), users and preferences (§7.9), locations (§7.8)."""
from __future__ import annotations

import math
from datetime import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import ApiError
from app.models.tables import (
    District,
    Field,
    KvkContact,
    PushSubscription,
    Taluka,
    User,
    UserPreferences,
    Village,
)
from app.schemas.bodies import OtpRequestBody, OtpVerifyBody, PreferencesPatchBody, RefreshBody, UserPatchBody
from app.security.deps import audit, current_user
from app.security.otp import normalize_phone, request_otp, verify_otp
from app.security.tokens import (
    issue_access_token,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.services.notify.channels import availability, send_sms

router = APIRouter()

DEFAULT_CHANNELS = {"whatsapp": False, "sms": True, "push": False}


def mask_phone(phone: str) -> str:
    d = phone.removeprefix("+91")
    return f"+91 {d[:2]}•••••{d[-3:]}" if len(d) == 10 else "+91 •••"


def district_kvk(db: Session, user: User) -> dict[str, str] | None:
    district_id = db.execute(
        select(Field.district_id).where(Field.user_id == user.id, Field.district_id.is_not(None)).limit(1)
    ).scalar_one_or_none()
    return kvk_for_district(db, district_id)


def kvk_for_district(db: Session, district_id: int | None) -> dict[str, str] | None:
    if district_id is None:
        return None
    row = db.execute(select(KvkContact).where(KvkContact.district_id == district_id).limit(1)).scalar_one_or_none()
    return {"name": row.name, "phone": row.phone} if row else None


def serialize_user(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "phone_masked": mask_phone(user.phone),
        "name": user.name,
        "role": user.role,
        "preferred_locale": user.preferred_locale,
        "temp_unit": user.temp_unit,
        "area_unit": user.area_unit,
        "district_kvk": district_kvk(db, user),
    }


def get_prefs(db: Session, user: User) -> UserPreferences:
    prefs = db.get(UserPreferences, user.id)
    if prefs is None:
        prefs = UserPreferences(user_id=user.id, channels=dict(DEFAULT_CHANNELS))
        db.add(prefs)
        db.flush()
    return prefs


def serialize_prefs(prefs: UserPreferences) -> dict:
    fmt = lambda t: t.strftime("%H:%M") if t else None
    return {
        "channels": {**DEFAULT_CHANNELS, **(prefs.channels or {})},
        "quiet_hours_start": fmt(prefs.quiet_hours_start),
        "quiet_hours_end": fmt(prefs.quiet_hours_end),
        "channel_availability": availability(),
        # ADDITIVE: development only; SMS "delivery" is a line in the dev outbox file, not a message to a phone.
        "sms_dev_outbox": get_settings().sms_provider == "dev_outbox" and not get_settings().is_production,
    }


# ---------- auth ----------
@router.post("/auth/otp/request", tags=["auth"])
def otp_request(body: OtpRequestBody, db: Session = Depends(get_db)) -> dict:
    phone = normalize_phone(body.phone)
    code, expires_in = request_otp(db, phone)
    s = get_settings()
    # Last line enables WebOTP autofill on Android Chrome (design.md 23.5).
    message = f"FasalAlert code: {code}. Valid for 5 minutes.\n\n@{s.web_otp_origin} #{code}"
    result = send_sms(phone, message)
    audit(db, None, "otp_request", "phone", None, provider=result.provider, status=result.status)
    if result.status != "sent":
        db.commit()
        raise ApiError("internal_error", "We could not send the SMS. Call 1800-180-1551 for help.",
                       {"reason": "sms_unavailable"}, status=503)
    out: dict = {"expires_in": expires_in, "retry_after": 60}
    if result.provider == "dev_outbox" and s.allow_demo_otp:
        # Demo/hackathon only: same code the server will verify. Never returned in production.
        out["delivery"] = "dev_outbox"
        out["demo_code"] = code
    elif result.provider == "dev_outbox":
        # Outbox on but demo visibility off: tell the UI SMS was not sent, without exposing the code.
        out["delivery"] = "dev_outbox"
    return out


@router.post("/auth/otp/verify", tags=["auth"])
def otp_verify(body: OtpVerifyBody, db: Session = Depends(get_db)) -> dict:
    phone = normalize_phone(body.phone)
    verify_otp(db, phone, body.code)
    user = db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
    is_new = user is None
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.flush()
        db.add(UserPreferences(user_id=user.id, channels=dict(DEFAULT_CHANNELS)))
    has_fields = db.execute(select(Field.id).where(Field.user_id == user.id).limit(1)).first() is not None
    audit(db, user.id, "signin", "user", str(user.id), new=is_new)
    return {
        "access_token": issue_access_token(user),
        "refresh_token": issue_refresh_token(db, user.id),
        "user": serialize_user(db, user),
        "is_new_user": is_new,
        "has_fields": has_fields,
    }


@router.post("/auth/refresh", tags=["auth"])
def auth_refresh(body: RefreshBody, db: Session = Depends(get_db)) -> dict:
    user, new_refresh = rotate_refresh_token(db, body.refresh_token)
    return {"access_token": issue_access_token(user), "refresh_token": new_refresh}


@router.post("/auth/logout", tags=["auth"], summary="ADDITIVE: revoke a refresh token (secure sign-out)")
def auth_logout(body: RefreshBody, db: Session = Depends(get_db)) -> dict:
    revoke_refresh_token(db, body.refresh_token)
    return {"ok": True}


# ---------- users ----------
@router.get("/users/me", tags=["users"])
def users_me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {**serialize_user(db, user), "preferences": serialize_prefs(get_prefs(db, user))}


@router.patch("/users/me", tags=["users"])
def users_me_patch(body: UserPatchBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(user, k, v)
    db.flush()
    out = {**serialize_user(db, user), "preferences": serialize_prefs(get_prefs(db, user))}
    if body.preferred_locale:
        # PRD §7.9: the session JWT is re-issued with the new locale.
        out["access_token"] = issue_access_token(user)
    return out


def _parse_time(v: str | None) -> time | None:
    if v is None:
        return None
    h, m = v.split(":")
    return time(int(h), int(m))


@router.patch("/users/me/preferences", tags=["users"])
def preferences_patch(body: PreferencesPatchBody, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    prefs = get_prefs(db, user)
    data = body.model_dump(exclude_unset=True)
    if "channels" in data and data["channels"] is not None:
        merged = {**DEFAULT_CHANNELS, **(prefs.channels or {})}
        avail = availability()
        for ch, on in data["channels"].items():
            if on is None:
                continue
            if on and not avail.get(ch, False):
                raise ApiError("validation_error", f"{ch} alerts are not available yet", {"field": f"channels.{ch}"})
            merged[ch] = on
        prefs.channels = merged
    if "quiet_hours_start" in data:
        prefs.quiet_hours_start = _parse_time(data["quiet_hours_start"])
    if "quiet_hours_end" in data:
        prefs.quiet_hours_end = _parse_time(data["quiet_hours_end"])
    if "push_subscription" in data:
        sub = body.push_subscription
        if sub is None:
            db.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id))
        else:
            existing = db.execute(select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint)).scalar_one_or_none()
            if existing is None:
                db.add(PushSubscription(user_id=user.id, endpoint=sub.endpoint, p256dh=sub.keys.p256dh, auth=sub.keys.auth))
            else:
                existing.user_id, existing.p256dh, existing.auth = user.id, sub.keys.p256dh, sub.keys.auth
    db.flush()
    return serialize_prefs(prefs)


# ---------- locations ----------
def _loc(row, with_point: bool = False) -> dict:  # type: ignore[no-untyped-def]
    out = {"id": row.id, "name": {"en": row.name_en, "mr": row.name_mr, "hi": row.name_hi}}
    if with_point:
        out["lat"], out["lon"] = row.lat, row.lon
    return out


@router.get("/locations/districts", tags=["locations"])
def districts(db: Session = Depends(get_db)) -> list[dict]:
    return [_loc(d) for d in db.execute(select(District).order_by(District.name_en)).scalars()]


@router.get("/locations/talukas", tags=["locations"])
def talukas(district_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(Taluka).where(Taluka.district_id == district_id).order_by(Taluka.name_en)).scalars()
    return [_loc(t) for t in rows]


@router.get("/locations/villages", tags=["locations"])
def villages(taluka_id: int = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(Village).where(Village.taluka_id == taluka_id).order_by(Village.name_en)).scalars()
    return [_loc(v, with_point=True) for v in rows]


@router.get("/locations/search", tags=["locations"], summary="ADDITIVE: find villages by name (onboarding map search)")
def search_villages(q: str = Query(..., min_length=2, max_length=60), limit: int = Query(12, ge=1, le=30),
                    db: Session = Depends(get_db)) -> list[dict]:
    term = q.strip()
    like = f"%{term}%"
    rows = db.execute(
        select(Village, Taluka, District).join(Taluka, Village.taluka_id == Taluka.id).join(District, Taluka.district_id == District.id)
        .where(or_(Village.name_en.ilike(like), Village.name_mr.ilike(like), Village.name_hi.ilike(like)))
        .order_by(func.lower(Village.name_en).startswith(term.lower()).desc(), func.length(Village.name_en), Village.name_en)
        .limit(limit)
    ).all()
    return [{**_loc(v, with_point=True), "taluka": _loc(t), "district": _loc(d)} for v, t, d in rows]


@router.get("/locations/nearest", tags=["locations"], summary="ADDITIVE: nearest village to a point (onboarding GPS)")
def nearest_village(lat: float = Query(..., ge=15.4, le=22.3), lon: float = Query(..., ge=72.4, le=81.1),
                    db: Session = Depends(get_db)) -> dict:
    box = 0.25  # about 25 km; a point further than that from every village is not matched to one
    k = math.cos(math.radians(lat)) ** 2
    dist2 = (Village.lat - lat) * (Village.lat - lat) + (Village.lon - lon) * (Village.lon - lon) * k
    row = db.execute(
        select(Village, Taluka, District).join(Taluka, Village.taluka_id == Taluka.id).join(District, Taluka.district_id == District.id)
        .where(Village.lat.between(lat - box, lat + box), Village.lon.between(lon - box, lon + box))
        .order_by(dist2).limit(1)
    ).first()
    if row is None:
        raise ApiError("not_found", "No village near this point", {"field": "lat"})
    v, t, d = row
    km = 111.32 * math.sqrt((v.lat - lat) ** 2 + ((v.lon - lon) ** 2) * k)
    return {"village": _loc(v, with_point=True), "taluka": _loc(t), "district": _loc(d), "distance_km": round(km, 2)}
