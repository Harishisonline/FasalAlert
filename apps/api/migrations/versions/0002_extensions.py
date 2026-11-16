"""Additions beyond the PRD §10 DDL: provenance columns, RAG documents and full-text search,
job state, push subscriptions, routes, KVK contacts, crop stages, reproducibility inputs.

Every addition is additive: no PRD column is renamed or dropped.

Revision ID: 0002_extensions
"""
from alembic import op

revision = "0002_extensions"
down_revision = "0001_prd_schema"
branch_labels = None
depends_on = None

SQL = r"""
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- Provenance on ingested data (PRD §8.4, data foundry) ----------
ALTER TABLE weather_observations
  ADD COLUMN source_url TEXT,
  ADD COLUMN licence    TEXT,
  ADD COLUMN fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN quality    TEXT NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok','suspect','missing'));

ALTER TABLE weather_forecasts
  ADD COLUMN model          TEXT,
  ADD COLUMN tmin_spread_c  DOUBLE PRECISION,
  ADD COLUMN tmax_spread_c  DOUBLE PRECISION,
  ADD COLUMN source_url     TEXT,
  ADD COLUMN licence        TEXT,
  ADD COLUMN fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX uq_forecast_point ON weather_forecasts (field_id, valid_date, issued_at, source);
CREATE INDEX idx_forecast_latlon ON weather_forecasts (lat, lon, valid_date);

ALTER TABLE mandi_markets
  ADD COLUMN state        TEXT,
  ADD COLUMN district_name TEXT,
  ADD COLUMN geocode_source TEXT;

ALTER TABLE mandi_prices
  ADD COLUMN source_url TEXT,
  ADD COLUMN licence    TEXT,
  ADD COLUMN fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN quality    TEXT NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok','suspect','missing'));

ALTER TABLE road_segments
  ADD COLUMN ref        TEXT,
  ADD COLUMN source     TEXT NOT NULL DEFAULT 'osm',
  ADD COLUMN slope_pct  DOUBLE PRECISION,
  ADD COLUMN low_lying  BOOLEAN,
  ADD COLUMN fetched_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE field_routes (
  id            BIGSERIAL PRIMARY KEY,
  field_id      BIGINT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  market_id     BIGINT REFERENCES mandi_markets(id) ON DELETE SET NULL,
  market_name   TEXT,
  segment_ids   BIGINT[] NOT NULL DEFAULT '{}',
  route_name    TEXT,
  distance_km   DOUBLE PRECISION,
  duration_min  DOUBLE PRECISION,
  source        TEXT NOT NULL,
  computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (field_id, market_name)
);

-- ---------- Ingestion runs and job state ----------
CREATE TABLE ingest_runs (
  id          BIGSERIAL PRIMARY KEY,
  source      TEXT NOT NULL,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed','skipped')),
  records     INT NOT NULL DEFAULT 0,
  params      JSONB NOT NULL DEFAULT '{}',
  error       TEXT
);
CREATE INDEX idx_ingest_runs_source ON ingest_runs (source, started_at DESC);

CREATE TABLE job_runs (
  id          BIGSERIAL PRIMARY KEY,
  job         TEXT NOT NULL,
  run_key     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed')),
  attempts    INT NOT NULL DEFAULT 1,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  detail      JSONB NOT NULL DEFAULT '{}',
  error       TEXT,
  UNIQUE (job, run_key)
);

-- ---------- Decisions: reproducibility ----------
ALTER TABLE decisions
  ADD COLUMN inputs          JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN policy_version  TEXT,
  ADD COLUMN payload         JSONB NOT NULL DEFAULT '{}';

ALTER TABLE risks
  ADD COLUMN method TEXT NOT NULL DEFAULT 'model' CHECK (method IN ('model','rule','observed','unavailable'));

-- ---------- Alerts: idempotency and quiet hours ----------
ALTER TABLE alerts
  ADD COLUMN dedupe_key   TEXT,
  ADD COLUMN queued_until TIMESTAMPTZ,
  ADD COLUMN detail       JSONB NOT NULL DEFAULT '{}';
CREATE UNIQUE INDEX uq_alerts_dedupe ON alerts (user_id, dedupe_key, channel) WHERE dedupe_key IS NOT NULL;

CREATE TABLE push_subscriptions (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint   TEXT NOT NULL UNIQUE,
  p256dh     TEXT NOT NULL,
  auth       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Advisory corpus (RAG) ----------
CREATE TABLE advisory_documents (
  doc_id               TEXT PRIMARY KEY,
  institution          TEXT NOT NULL,
  title                TEXT NOT NULL,
  source_url           TEXT NOT NULL,
  landing_url          TEXT,
  year                 INT,
  crops                TEXT[] NOT NULL DEFAULT '{}',
  topics               TEXT[] NOT NULL DEFAULT '{}',
  lang                 TEXT NOT NULL,
  license              TEXT NOT NULL,
  license_evidence_url TEXT,
  license_verified     BOOLEAN NOT NULL DEFAULT false,
  sha256               TEXT NOT NULL,
  local_path           TEXT,
  retrieved_at         TIMESTAMPTZ,
  ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  verified             BOOLEAN NOT NULL DEFAULT false
);

ALTER TABLE advisory_chunks
  ADD COLUMN chunk_index     INT NOT NULL DEFAULT 0,
  ADD COLUMN topics          TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN content_hash    TEXT,
  ADD COLUMN embedding_model TEXT,
  ADD COLUMN page            INT,
  ADD COLUMN content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
CREATE UNIQUE INDEX uq_chunks_hash ON advisory_chunks (content_hash);
CREATE INDEX idx_chunks_tsv ON advisory_chunks USING GIN (content_tsv);
CREATE INDEX idx_chunks_doc ON advisory_chunks (doc_id, chunk_index);
CREATE INDEX idx_chunks_crop ON advisory_chunks (crop);

-- ---------- Reference data ----------
CREATE TABLE kvk_contacts (
  id          BIGSERIAL PRIMARY KEY,
  district_id BIGINT REFERENCES districts(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  phone       TEXT NOT NULL,
  source_url  TEXT NOT NULL,
  verified_at DATE NOT NULL
);

CREATE TABLE crop_stages (
  crop        TEXT NOT NULL,
  stage       TEXT NOT NULL,
  ord         INT NOT NULL,
  method      TEXT NOT NULL,
  start_val   DOUBLE PRECISION,
  end_val     DOUBLE PRECISION,
  labels      JSONB NOT NULL,
  thresholds  JSONB NOT NULL DEFAULT '{}',
  source      JSONB NOT NULL DEFAULT '{}',
  version     TEXT NOT NULL,
  PRIMARY KEY (crop, stage)
);

CREATE TABLE public_district_risks (
  id            BIGSERIAL PRIMARY KEY,
  district_id   BIGINT NOT NULL REFERENCES districts(id) ON DELETE CASCADE,
  risk_date     DATE NOT NULL,
  payload       JSONB NOT NULL,
  model_version TEXT NOT NULL,
  computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (district_id, risk_date)
);

CREATE TABLE district_boundaries (
  district_id BIGINT PRIMARY KEY REFERENCES districts(id) ON DELETE CASCADE,
  geom        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
  source      TEXT NOT NULL,
  source_url  TEXT NOT NULL,
  licence     TEXT NOT NULL
);
CREATE INDEX idx_district_boundaries_geom ON district_boundaries USING GIST (geom);

ALTER TABLE districts ADD COLUMN source_url TEXT;
"""

DOWN = r"""
DROP TABLE IF EXISTS district_boundaries, public_district_risks, crop_stages, kvk_contacts,
  advisory_documents, push_subscriptions, job_runs, ingest_runs, field_routes CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
