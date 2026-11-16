"""Delivery channels: SMS (guaranteed), Web Push (guaranteed), WhatsApp (only when configured).

Honesty rule: a delivery is reported as "sent" only when a real provider accepted it. The development
outbox writes to a local file, is labelled provider="dev_outbox", and refuses to run in production.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import DATA_DIR, get_settings
from app.core.timeutil import now_utc

log = logging.getLogger("fasalalert.notify")


@dataclass(frozen=True)
class DeliveryResult:
    status: str          # "sent" | "failed"
    provider: str        # "twilio" | "dev_outbox" | "webpush" | "meta_cloud" | "none"
    provider_sid: str | None = None
    error: str | None = None


def _mask(phone: str) -> str:
    return phone[:5] + "•" * max(0, len(phone) - 8) + phone[-3:]


def sms_configured() -> bool:
    s = get_settings()
    if s.sms_provider == "twilio":
        return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number)
    return s.sms_provider == "dev_outbox" and not s.is_production


def send_sms(phone: str, body: str) -> DeliveryResult:
    s = get_settings()
    if s.sms_provider == "twilio":
        if not sms_configured():
            return DeliveryResult("failed", "twilio", error="TWILIO_* settings missing")
        try:
            r = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                auth=(s.twilio_account_sid, s.twilio_auth_token),
                data={"To": phone, "From": s.twilio_from_number, "Body": body},
                timeout=15,
            )
            if r.status_code in (200, 201):
                return DeliveryResult("sent", "twilio", provider_sid=r.json().get("sid"))
            return DeliveryResult("failed", "twilio", error=f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            return DeliveryResult("failed", "twilio", error=type(e).__name__)
    if s.sms_provider == "dev_outbox":
        if s.is_production:
            return DeliveryResult("failed", "dev_outbox", error="dev_outbox is disabled in production")
        path = dev_outbox_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"to": phone, "body": body, "at": now_utc().isoformat()}, ensure_ascii=False) + "\n")
        log.info("sms written to dev outbox for %s", _mask(phone))
        return DeliveryResult("sent", "dev_outbox", provider_sid="dev-outbox")
    return DeliveryResult("failed", "none", error="No SMS provider configured (SMS_PROVIDER)")


def push_configured() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def send_web_push(subscription: dict, payload: dict) -> DeliveryResult:
    if not push_configured():
        return DeliveryResult("failed", "webpush", error="VAPID keys not configured")
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        resp = webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": s.vapid_subject},
            timeout=15,
        )
        return DeliveryResult("sent", "webpush", provider_sid=str(getattr(resp, "status_code", "")))
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return DeliveryResult("failed", "webpush", error=f"push rejected ({code})" if code else "push rejected")


def whatsapp_configured() -> bool:
    s = get_settings()
    return s.whatsapp_provider == "meta_cloud" and bool(s.whatsapp_token and s.whatsapp_phone_number_id)


def send_whatsapp(phone: str, body: str) -> DeliveryResult:
    """Meta WhatsApp Cloud API text message. Business-initiated messages outside the 24 h window need
    approved templates; this adapter sends plain text and reports the provider's answer honestly."""
    s = get_settings()
    if not whatsapp_configured():
        return DeliveryResult("failed", "none", error="WhatsApp not configured")
    try:
        r = httpx.post(
            f"https://graph.facebook.com/v21.0/{s.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {s.whatsapp_token}"},
            json={"messaging_product": "whatsapp", "to": phone.lstrip("+"), "type": "text", "text": {"body": body}},
            timeout=15,
        )
        if r.status_code == 200:
            msgs = r.json().get("messages") or [{}]
            return DeliveryResult("sent", "meta_cloud", provider_sid=msgs[0].get("id"))
        return DeliveryResult("failed", "meta_cloud", error=f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        return DeliveryResult("failed", "meta_cloud", error=type(e).__name__)


def availability() -> dict[str, bool]:
    return {"sms": sms_configured(), "push": push_configured(), "whatsapp": whatsapp_configured()}


def dev_outbox_path() -> Path:
    custom = get_settings().dev_outbox_dir
    return (Path(custom) if custom else DATA_DIR / "dev_outbox") / "sms.jsonl"
