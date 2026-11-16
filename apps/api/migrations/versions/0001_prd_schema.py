"""PRD §10 schema, verbatim (see migrations/sql/0001_prd_schema.sql).

Revision ID: 0001_prd_schema
"""
from pathlib import Path

from alembic import op

revision = "0001_prd_schema"
down_revision = None
branch_labels = None
depends_on = None

SQL = (Path(__file__).resolve().parents[1] / "sql" / "0001_prd_schema.sql").read_text(encoding="utf-8")

TABLES = [
    "audit_log", "fpo_comments", "fpo_posts", "fpo_members", "fpos", "model_registry", "advisory_chunks",
    "alert_deliveries", "alerts", "decisions", "risks", "route_risks", "road_segments", "mandi_prices",
    "mandi_markets", "weather_forecasts", "weather_observations", "field_calibration", "fields", "villages",
    "talukas", "districts", "user_preferences", "refresh_tokens", "otp_codes", "users",
]


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
