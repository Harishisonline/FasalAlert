-- Copied verbatim from PRD.md §10 except the two lines marked FIX.
-- 01_schema.sql: FasalAlert
-- Order: users → fields → calibration → weather → prices → roads →
--        risks → alerts → advisory corpus → models → FPO → audit

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS postgis;
-- FIX: vector(768) below needs pgvector; the PRD DDL omitted this line.
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- USERS AND AUTH ----------
CREATE TABLE users (
  id                BIGSERIAL PRIMARY KEY,
  phone             TEXT UNIQUE NOT NULL,
  name              TEXT,
  role              TEXT NOT NULL DEFAULT 'farmer'
                    CHECK (role IN ('farmer','fpo_manager','admin')),
  preferred_locale  TEXT NOT NULL DEFAULT 'mr'
                    CHECK (preferred_locale IN ('en','mr','hi')),
  temp_unit         TEXT NOT NULL DEFAULT 'celsius'
                    CHECK (temp_unit IN ('celsius','fahrenheit')),
  area_unit         TEXT NOT NULL DEFAULT 'hectare'
                    CHECK (area_unit IN ('hectare','acre')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE otp_codes (
  id            BIGSERIAL PRIMARY KEY,
  phone         TEXT NOT NULL,
  code_hash     TEXT NOT NULL,
  attempts      INT  NOT NULL DEFAULT 0,
  max_attempts  INT  NOT NULL DEFAULT 5,
  expires_at    TIMESTAMPTZ NOT NULL,
  consumed_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_otp_phone_created ON otp_codes (phone, created_at DESC);

CREATE TABLE refresh_tokens (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,
  revoked_at  TIMESTAMPTZ,
  expires_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_user ON refresh_tokens (user_id);

CREATE TABLE user_preferences (
  user_id           BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  channels          JSONB NOT NULL DEFAULT '{"whatsapp":false,"sms":true,"push":false}',
  quiet_hours_start TIME,
  quiet_hours_end   TIME,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- GEOGRAPHY ----------
CREATE TABLE districts (
  id       BIGSERIAL PRIMARY KEY,
  code     TEXT UNIQUE NOT NULL,
  name_en  TEXT NOT NULL,
  name_mr  TEXT NOT NULL,
  name_hi  TEXT NOT NULL,
  centroid GEOGRAPHY(POINT, 4326) NOT NULL,
  agrozone TEXT
);

CREATE TABLE talukas (
  id         BIGSERIAL PRIMARY KEY,
  district_id BIGINT NOT NULL REFERENCES districts(id) ON DELETE CASCADE,
  code       TEXT UNIQUE NOT NULL,
  name_en    TEXT NOT NULL,
  name_mr    TEXT NOT NULL,
  name_hi    TEXT NOT NULL,
  centroid   GEOGRAPHY(POINT, 4326) NOT NULL
);
CREATE INDEX idx_talukas_district ON talukas (district_id);

CREATE TABLE villages (
  id         BIGSERIAL PRIMARY KEY,
  taluka_id  BIGINT NOT NULL REFERENCES talukas(id) ON DELETE CASCADE,
  name_en    TEXT NOT NULL,
  name_mr    TEXT NOT NULL,
  name_hi    TEXT NOT NULL,
  lat        DOUBLE PRECISION NOT NULL,
  lon        DOUBLE PRECISION NOT NULL
);
CREATE INDEX idx_villages_taluka ON villages (taluka_id);
CREATE INDEX idx_villages_geo ON villages USING GIST (ST_SetSRID(ST_MakePoint(lon, lat), 4326));

-- ---------- FIELDS ----------
CREATE TABLE fields (
  id             BIGSERIAL PRIMARY KEY,
  user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name           TEXT,
  crop           TEXT NOT NULL
                 CHECK (crop IN ('mango','pomegranate','grape','soybean','cotton','sugarcane')),
  variety        TEXT,
  sowing_date    DATE,
  lat            DOUBLE PRECISION NOT NULL,
  lon            DOUBLE PRECISION NOT NULL,
  area_sqm       DOUBLE PRECISION,
  village_id     BIGINT REFERENCES villages(id) ON DELETE SET NULL,
  taluka_id      BIGINT REFERENCES talukas(id) ON DELETE SET NULL,
  district_id    BIGINT REFERENCES districts(id) ON DELETE SET NULL,
  primary_mandi  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fields_user ON fields (user_id);
CREATE INDEX idx_fields_geo ON fields USING GIST (ST_SetSRID(ST_MakePoint(lon, lat), 4326));

CREATE TABLE field_calibration (
  field_id            BIGINT PRIMARY KEY REFERENCES fields(id) ON DELETE CASCADE,
  sensitivity         TEXT NOT NULL DEFAULT 'normal'
                      CHECK (sensitivity IN ('low','normal','high')),
  frost_threshold_c   DOUBLE PRECISION,
  heat_threshold_c    DOUBLE PRECISION,
  harvest_lead_hours  INT NOT NULL DEFAULT 24,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- WEATHER AND OBSERVATIONS ----------
CREATE TABLE weather_observations (
  id            BIGSERIAL PRIMARY KEY,
  station_id    TEXT,
  station_name  TEXT,
  lat           DOUBLE PRECISION NOT NULL,
  lon           DOUBLE PRECISION NOT NULL,
  obs_date      DATE NOT NULL,
  tmin_c        DOUBLE PRECISION,
  tmax_c        DOUBLE PRECISION,
  rain_mm       DOUBLE PRECISION,
  source        TEXT NOT NULL,
  UNIQUE (station_id, obs_date, source)
);
CREATE INDEX idx_weather_obs_date ON weather_observations (obs_date);
CREATE INDEX idx_weather_geo ON weather_observations USING GIST (ST_SetSRID(ST_MakePoint(lon, lat), 4326));

CREATE TABLE weather_forecasts (
  id            BIGSERIAL PRIMARY KEY,
  field_id      BIGINT REFERENCES fields(id) ON DELETE CASCADE,
  lat           DOUBLE PRECISION NOT NULL,
  lon           DOUBLE PRECISION NOT NULL,
  issued_at     TIMESTAMPTZ NOT NULL,
  valid_date    DATE NOT NULL,
  lead_hours    INT NOT NULL,
  tmin_c        DOUBLE PRECISION,
  tmax_c        DOUBLE PRECISION,
  rain_mm       DOUBLE PRECISION,
  precip_prob   DOUBLE PRECISION,
  source        TEXT NOT NULL
);
CREATE INDEX idx_forecast_field_date ON weather_forecasts (field_id, valid_date);

-- ---------- MARKET ----------
CREATE TABLE mandi_markets (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  commodity  TEXT NOT NULL,
  district_id BIGINT REFERENCES districts(id) ON DELETE SET NULL,
  lat        DOUBLE PRECISION,
  lon        DOUBLE PRECISION,
  UNIQUE (name, commodity)
);

CREATE TABLE mandi_prices (
  id             BIGSERIAL PRIMARY KEY,
  market_id      BIGINT NOT NULL REFERENCES mandi_markets(id) ON DELETE CASCADE,
  commodity      TEXT NOT NULL,
  price_date     DATE NOT NULL,
  min_rs_qtl     DOUBLE PRECISION,
  modal_rs_qtl   DOUBLE PRECISION,
  max_rs_qtl     DOUBLE PRECISION,
  arrival_qtl    DOUBLE PRECISION,
  source         TEXT NOT NULL DEFAULT 'agmarknet',
  UNIQUE (market_id, commodity, price_date)
);
CREATE INDEX idx_prices_lookup ON mandi_prices (commodity, price_date DESC);

-- ---------- TRANSPORT ----------
CREATE TABLE road_segments (
  id          BIGSERIAL PRIMARY KEY,
  osm_id      BIGINT UNIQUE NOT NULL,
  name        TEXT,
  road_class  TEXT NOT NULL
              CHECK (road_class IN ('national','state','district','village','other')),
  -- FIX: PRD wrote "LINESTRING", which is not a PostgreSQL type; PostGIS spelling below.
  geom        GEOMETRY(LINESTRING, 4326) NOT NULL,
  min_elev_m  DOUBLE PRECISION,
  max_elev_m  DOUBLE PRECISION,
  length_km   DOUBLE PRECISION
);
CREATE INDEX idx_road_geom ON road_segments USING GIST (geom);

CREATE TABLE route_risks (
  id              BIGSERIAL PRIMARY KEY,
  field_id        BIGINT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  segment_id      BIGINT NOT NULL REFERENCES road_segments(id) ON DELETE CASCADE,
  valid_date      DATE NOT NULL,
  p_disruption    DOUBLE PRECISION NOT NULL,
  rain_accum_mm   DOUBLE PRECISION,
  model_version   TEXT NOT NULL,
  computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (field_id, segment_id, valid_date)
);

-- ---------- RISKS, DECISIONS, ALERTS ----------
CREATE TABLE risks (
  id             BIGSERIAL PRIMARY KEY,
  field_id       BIGINT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL
                 CHECK (kind IN ('frost','heatwave','heavy_rain','dry_spell','transport')),
  level          TEXT NOT NULL CHECK (level IN ('none','low','medium','high','critical')),
  probability    DOUBLE PRECISION,
  tmin_band_low  DOUBLE PRECISION,
  tmin_band_high DOUBLE PRECISION,
  threshold_c    DOUBLE PRECISION,
  window_start   TIMESTAMPTZ,
  window_end     TIMESTAMPTZ,
  lead_hours     INT,
  evidence       JSONB NOT NULL DEFAULT '{}',
  model_version  TEXT NOT NULL,
  computed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_risks_field ON risks (field_id, computed_at DESC);

CREATE TABLE decisions (
  id              BIGSERIAL PRIMARY KEY,
  field_id        BIGINT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  decision_date   DATE NOT NULL,
  headline        TEXT NOT NULL,
  action_text     TEXT NOT NULL,
  action_by       TIMESTAMPTZ,
  confidence      DOUBLE PRECISION,
  abstain_reason  TEXT,
  risk_ids        BIGINT[] NOT NULL DEFAULT '{}',
  price_summary   JSONB NOT NULL DEFAULT '{}',
  transport_summary JSONB NOT NULL DEFAULT '{}',
  sources         JSONB NOT NULL DEFAULT '[]',
  model_versions  JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (field_id, decision_date)
);

CREATE TABLE alerts (
  id             BIGSERIAL PRIMARY KEY,
  user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  field_id       BIGINT REFERENCES fields(id) ON DELETE CASCADE,
  decision_id    BIGINT REFERENCES decisions(id) ON DELETE CASCADE,
  risk_id        BIGINT REFERENCES risks(id) ON DELETE SET NULL,
  kind           TEXT NOT NULL,
  level          TEXT NOT NULL,
  message        TEXT NOT NULL,
  channel        TEXT NOT NULL,
  sent_at        TIMESTAMPTZ,
  read_at        TIMESTAMPTZ,
  feedback       INT CHECK (feedback IN (-1, 1)),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_user ON alerts (user_id, created_at DESC);

CREATE TABLE alert_deliveries (
  id         BIGSERIAL PRIMARY KEY,
  alert_id   BIGINT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  channel    TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN ('queued','sent','failed','read')),
  provider_sid TEXT,
  error      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- ADVISORY CORPUS ----------
CREATE TABLE advisory_chunks (
  id          BIGSERIAL PRIMARY KEY,
  doc_id      TEXT NOT NULL,
  institution TEXT NOT NULL,
  title       TEXT NOT NULL,
  year        INT,
  lang        TEXT NOT NULL DEFAULT 'en',
  crop        TEXT,
  stage       TEXT,
  source_url  TEXT NOT NULL,
  license     TEXT NOT NULL,
  verified    BOOLEAN NOT NULL DEFAULT false,
  embedding   vector(768),
  content     TEXT NOT NULL
);
CREATE INDEX idx_chunks_ivfflat ON advisory_chunks
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_verified ON advisory_chunks (verified) WHERE verified;

-- ---------- MODEL REGISTRY ----------
CREATE TABLE model_registry (
  name         TEXT NOT NULL,
  version      TEXT NOT NULL,
  kind         TEXT NOT NULL,
  dataset_ref  TEXT NOT NULL,
  trained_at   TIMESTAMPTZ NOT NULL,
  metrics      JSONB NOT NULL,
  thresholds   JSONB NOT NULL,
  artifact_path TEXT NOT NULL,
  notes        TEXT,
  PRIMARY KEY (name, version)
);

-- ---------- FPO ----------
CREATE TABLE fpos (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  district_id  BIGINT REFERENCES districts(id) ON DELETE SET NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fpo_members (
  id         BIGSERIAL PRIMARY KEY,
  fpo_id     BIGINT NOT NULL REFERENCES fpos(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member','manager')),
  joined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (fpo_id, user_id)
);

CREATE TABLE fpo_posts (
  id          BIGSERIAL PRIMARY KEY,
  fpo_id      BIGINT NOT NULL REFERENCES fpos(id) ON DELETE CASCADE,
  author_id   BIGINT REFERENCES users(id) ON DELETE SET NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('question','advisory','announcement')),
  title       TEXT NOT NULL,
  body_md     TEXT NOT NULL,
  locale      TEXT NOT NULL DEFAULT 'mr',
  pinned      BOOLEAN NOT NULL DEFAULT false,
  deleted_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fpo_posts ON fpo_posts (fpo_id, pinned DESC, created_at DESC);

CREATE TABLE fpo_comments (
  id         BIGSERIAL PRIMARY KEY,
  post_id    BIGINT NOT NULL REFERENCES fpo_posts(id) ON DELETE CASCADE,
  author_id  BIGINT REFERENCES users(id) ON DELETE SET NULL,
  body       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- AUDIT ----------
CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action      TEXT NOT NULL,
  entity      TEXT NOT NULL,
  entity_id   TEXT,
  detail      JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_user_time ON audit_log (user_id, created_at DESC);
