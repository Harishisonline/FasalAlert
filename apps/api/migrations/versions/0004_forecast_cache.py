"""Cached raw district forecasts, so the public board can be recomputed without the weather API.

Open-Meteo rate limits by IP address, and a serverless function's egress IP is shared with every
other tenant on it (their terms say Vercel users are limited earlier than expected). A board
refresh that can only run from that IP fails with 429, so the raw multi-point forecast is stored
here when it succeeds and reused on the next refresh. One row per district per fetch day: the
board reads the next three days at once, so the whole block is kept together.

Revision ID: 0004_forecast_cache
"""
from alembic import op

revision = "0004_forecast_cache"
down_revision = "0003_ask_threads"
branch_labels = None
depends_on = None

SQL = r"""
CREATE TABLE district_forecast_cache (
  id            BIGSERIAL PRIMARY KEY,
  district_id   BIGINT NOT NULL REFERENCES districts(id) ON DELETE CASCADE,
  valid_date    DATE NOT NULL,
  issued_at     TIMESTAMPTZ NOT NULL,
  payload       JSONB NOT NULL,
  source        TEXT NOT NULL DEFAULT 'open-meteo',
  source_url    TEXT,
  licence       TEXT,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (district_id, valid_date)
);
CREATE INDEX ix_district_forecast_cache_date ON district_forecast_cache (valid_date DESC);
"""

DOWN = r"""
DROP TABLE IF EXISTS district_forecast_cache;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
