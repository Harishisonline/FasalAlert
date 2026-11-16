"""Request bodies (PRD §11). Response shapes are documented in packages/shared/api.ts and docs/API.md."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Locale = Literal["en", "mr", "hi"]
CropKey = Literal["mango", "pomegranate", "grape", "soybean", "cotton", "sugarcane"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OtpRequestBody(Strict):
    phone: str = Field(min_length=10, max_length=20)


class OtpVerifyBody(Strict):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=6, max_length=6)


class RefreshBody(Strict):
    refresh_token: str = Field(min_length=20, max_length=200)


class UserPatchBody(Strict):
    name: str | None = Field(default=None, max_length=60)
    preferred_locale: Locale | None = None
    temp_unit: Literal["celsius", "fahrenheit"] | None = None
    area_unit: Literal["hectare", "acre"] | None = None


class ChannelsPatch(Strict):
    whatsapp: bool | None = None
    sms: bool | None = None
    push: bool | None = None


class PushKeys(Strict):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscriptionBody(Strict):
    endpoint: str = Field(max_length=1000)
    keys: PushKeys


class PreferencesPatchBody(Strict):
    channels: ChannelsPatch | None = None
    quiet_hours_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    push_subscription: PushSubscriptionBody | None = None


class FieldCreateBody(Strict):
    crop: CropKey
    variety: str | None = Field(default=None, max_length=60)
    sowing_date: date | None = None
    lat: float = Field(ge=15.4, le=22.3)   # Maharashtra bounding box with margin
    lon: float = Field(ge=72.4, le=81.1)
    name: str | None = Field(default=None, max_length=60)
    village_id: int | None = None
    taluka_id: int | None = None
    district_id: int | None = None
    area_sqm: float | None = Field(default=None, gt=0, le=5_000_000)

    @field_validator("sowing_date")
    @classmethod
    def not_future(cls, v: date | None) -> date | None:
        from app.core.timeutil import today_ist

        if v is not None and v > today_ist():
            raise ValueError("Sowing date cannot be in the future")
        return v


class FieldPatchBody(Strict):
    crop: CropKey | None = None
    variety: str | None = Field(default=None, max_length=60)
    sowing_date: date | None = None
    lat: float | None = Field(default=None, ge=15.4, le=22.3)
    lon: float | None = Field(default=None, ge=72.4, le=81.1)
    name: str | None = Field(default=None, max_length=60)
    village_id: int | None = None
    taluka_id: int | None = None
    district_id: int | None = None
    area_sqm: float | None = Field(default=None, gt=0, le=5_000_000)
    primary_mandi: str | None = Field(default=None, max_length=120)

    @field_validator("sowing_date")
    @classmethod
    def not_future(cls, v: date | None) -> date | None:
        return FieldCreateBody.not_future(v)


class CalibrationPatchBody(Strict):
    sensitivity: Literal["low", "normal", "high"] | None = None
    frost_threshold_c: float | None = Field(default=None, ge=-10, le=20)
    heat_threshold_c: float | None = Field(default=None, ge=25, le=55)
    harvest_lead_hours: int | None = Field(default=None, ge=6, le=168)


class AskBody(Strict):
    text: str | None = Field(default=None, max_length=500)
    audio_b64: str | None = Field(default=None, max_length=4_000_000)  # about 3 MB of audio
    audio_mime: str | None = Field(default=None, max_length=60)
    field_id: int | None = None
    locale: Locale
    # ADDITIVE: the conversation to add this question to (none starts a new one), and a client id for Stop.
    thread_id: int | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ThreadPatchBody(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None


class CancelAskBody(Strict):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class FeedbackBody(Strict):
    value: Literal[-1, 1]


class FpoPostBody(Strict):
    kind: Literal["question", "advisory", "announcement"]
    title: str = Field(min_length=1, max_length=140)
    body_md: str = Field(min_length=1, max_length=5000)
    locale: Locale
    pinned: bool | None = None
