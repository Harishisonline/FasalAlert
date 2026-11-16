"""ORM mappings for the schema created by migrations 0001 (PRD §10) and 0002 (additions).

The migrations are the source of truth for DDL; these classes only map existing tables.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from geoalchemy2 import Geography, Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------- users and auth ----------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phone: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="farmer")
    preferred_locale: Mapped[str] = mapped_column(Text, default="mr")
    temp_unit: Mapped[str] = mapped_column(Text, default="celsius")
    area_unit: Mapped[str] = mapped_column(Text, default="hectare")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phone: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    channels: Mapped[dict[str, bool]] = mapped_column(JSONB)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- geography ----------
class District(Base):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_mr: Mapped[str] = mapped_column(Text)
    name_hi: Mapped[str] = mapped_column(Text)
    centroid: Mapped[Any] = mapped_column(Geography("POINT", srid=4326))
    agrozone: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class DistrictBoundary(Base):
    __tablename__ = "district_boundaries"
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id", ondelete="CASCADE"), primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    source: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    licence: Mapped[str] = mapped_column(Text)


class Taluka(Base):
    __tablename__ = "talukas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text, unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_mr: Mapped[str] = mapped_column(Text)
    name_hi: Mapped[str] = mapped_column(Text)
    centroid: Mapped[Any] = mapped_column(Geography("POINT", srid=4326))


class Village(Base):
    __tablename__ = "villages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    taluka_id: Mapped[int] = mapped_column(ForeignKey("talukas.id", ondelete="CASCADE"))
    name_en: Mapped[str] = mapped_column(Text)
    name_mr: Mapped[str] = mapped_column(Text)
    name_hi: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)


class KvkContact(Base):
    __tablename__ = "kvk_contacts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[date] = mapped_column(Date)


# ---------- fields ----------
class Field(Base):
    __tablename__ = "fields"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(Text)
    crop: Mapped[str] = mapped_column(Text)
    variety: Mapped[str | None] = mapped_column(Text)
    sowing_date: Mapped[date | None] = mapped_column(Date)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    area_sqm: Mapped[float | None] = mapped_column(Double)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id", ondelete="SET NULL"))
    taluka_id: Mapped[int | None] = mapped_column(ForeignKey("talukas.id", ondelete="SET NULL"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id", ondelete="SET NULL"))
    primary_mandi: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class FieldCalibration(Base):
    __tablename__ = "field_calibration"
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), primary_key=True)
    sensitivity: Mapped[str] = mapped_column(Text, default="normal")
    frost_threshold_c: Mapped[float | None] = mapped_column(Double)
    heat_threshold_c: Mapped[float | None] = mapped_column(Double)
    harvest_lead_hours: Mapped[int] = mapped_column(Integer, default=24)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- weather ----------
class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station_id: Mapped[str | None] = mapped_column(Text)
    station_name: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    obs_date: Mapped[date] = mapped_column(Date)
    tmin_c: Mapped[float | None] = mapped_column(Double)
    tmax_c: Mapped[float | None] = mapped_column(Double)
    rain_mm: Mapped[float | None] = mapped_column(Double)
    source: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    quality: Mapped[str] = mapped_column(Text, default="ok")


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_date: Mapped[date] = mapped_column(Date)
    lead_hours: Mapped[int] = mapped_column(Integer)
    tmin_c: Mapped[float | None] = mapped_column(Double)
    tmax_c: Mapped[float | None] = mapped_column(Double)
    rain_mm: Mapped[float | None] = mapped_column(Double)
    precip_prob: Mapped[float | None] = mapped_column(Double)
    source: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    tmin_spread_c: Mapped[float | None] = mapped_column(Double)
    tmax_spread_c: Mapped[float | None] = mapped_column(Double)
    source_url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- market ----------
class MandiMarket(Base):
    __tablename__ = "mandi_markets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    commodity: Mapped[str] = mapped_column(Text)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id", ondelete="SET NULL"))
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    state: Mapped[str | None] = mapped_column(Text)
    district_name: Mapped[str | None] = mapped_column(Text)
    geocode_source: Mapped[str | None] = mapped_column(Text)


class MandiPrice(Base):
    __tablename__ = "mandi_prices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("mandi_markets.id", ondelete="CASCADE"))
    commodity: Mapped[str] = mapped_column(Text)
    price_date: Mapped[date] = mapped_column(Date)
    min_rs_qtl: Mapped[float | None] = mapped_column(Double)
    modal_rs_qtl: Mapped[float | None] = mapped_column(Double)
    max_rs_qtl: Mapped[float | None] = mapped_column(Double)
    arrival_qtl: Mapped[float | None] = mapped_column(Double)
    source: Mapped[str] = mapped_column(Text, default="agmarknet")
    source_url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    quality: Mapped[str] = mapped_column(Text, default="ok")


# ---------- transport ----------
class RoadSegment(Base):
    __tablename__ = "road_segments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    osm_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    road_class: Mapped[str] = mapped_column(Text)
    geom: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=4326))
    min_elev_m: Mapped[float | None] = mapped_column(Double)
    max_elev_m: Mapped[float | None] = mapped_column(Double)
    length_km: Mapped[float | None] = mapped_column(Double)
    ref: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="osm")
    slope_pct: Mapped[float | None] = mapped_column(Double)
    low_lying: Mapped[bool | None] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class FieldRoute(Base):
    __tablename__ = "field_routes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    market_id: Mapped[int | None] = mapped_column(ForeignKey("mandi_markets.id", ondelete="SET NULL"))
    market_name: Mapped[str | None] = mapped_column(Text)
    segment_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    route_name: Mapped[str | None] = mapped_column(Text)
    distance_km: Mapped[float | None] = mapped_column(Double)
    duration_min: Mapped[float | None] = mapped_column(Double)
    source: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class RouteRisk(Base):
    __tablename__ = "route_risks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    segment_id: Mapped[int] = mapped_column(ForeignKey("road_segments.id", ondelete="CASCADE"))
    valid_date: Mapped[date] = mapped_column(Date)
    p_disruption: Mapped[float] = mapped_column(Double)
    rain_accum_mm: Mapped[float | None] = mapped_column(Double)
    model_version: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- risks, decisions, alerts ----------
class RiskRow(Base):
    __tablename__ = "risks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    probability: Mapped[float | None] = mapped_column(Double)
    tmin_band_low: Mapped[float | None] = mapped_column(Double)
    tmin_band_high: Mapped[float | None] = mapped_column(Double)
    threshold_c: Mapped[float | None] = mapped_column(Double)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_hours: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_version: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text, default="model")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    decision_date: Mapped[date] = mapped_column(Date)
    headline: Mapped[str] = mapped_column(Text)
    action_text: Mapped[str] = mapped_column(Text)
    action_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Double)
    abstain_reason: Mapped[str | None] = mapped_column(Text)
    risk_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    price_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    transport_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    policy_version: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"))
    risk_id: Mapped[int | None] = mapped_column(ForeignKey("risks.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    queued_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    provider_sid: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- advisory corpus ----------
class AdvisoryDocument(Base):
    __tablename__ = "advisory_documents"
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    institution: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    landing_url: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    crops: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    lang: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    license_evidence_url: Mapped[str | None] = mapped_column(Text)
    license_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class AdvisoryChunk(Base):
    __tablename__ = "advisory_chunks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text)
    institution: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    lang: Mapped[str] = mapped_column(Text, default="en")
    crop: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    content_hash: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)


# ---------- models, reference, public ----------
class ModelRegistry(Base):
    __tablename__ = "model_registry"
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    dataset_ref: Mapped[str] = mapped_column(Text)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifact_path: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class CropStage(Base):
    __tablename__ = "crop_stages"
    crop: Mapped[str] = mapped_column(Text, primary_key=True)
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    ord: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(Text)
    start_val: Mapped[float | None] = mapped_column(Double)
    end_val: Mapped[float | None] = mapped_column(Double)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[str] = mapped_column(Text)


class PublicDistrictRisk(Base):
    __tablename__ = "public_district_risks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id", ondelete="CASCADE"))
    risk_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="running")
    records: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(Text)
    run_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="running")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


# ---------- FPO and audit ----------
class Fpo(Base):
    __tablename__ = "fpos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class FpoMember(Base):
    __tablename__ = "fpo_members"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fpo_id: Mapped[int] = mapped_column(ForeignKey("fpos.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class FpoPost(Base):
    __tablename__ = "fpo_posts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fpo_id: Mapped[int] = mapped_column(ForeignKey("fpos.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, default="mr")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text)
    entity: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


# ---------- assistant conversations (migration 0003, ADDITIVE) ----------
class AskThread(Base):
    __tablename__ = "ask_threads"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id", ondelete="SET NULL"))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class AskMessage(Base):
    __tablename__ = "ask_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("ask_threads.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
