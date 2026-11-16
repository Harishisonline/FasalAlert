"""Test setup: the real PostGIS test database (fasalalert_test), dev SMS outbox, no external providers."""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("APP_ENV", "test")
os.environ["SMS_PROVIDER"] = "dev_outbox"
# A separate outbox: the suite deletes it between tests and must never touch the dev server's codes.
os.environ["DEV_OUTBOX_DIR"] = os.path.join(tempfile.gettempdir(), "fasalalert-test-outbox")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://fasalalert:fasalalert_dev@localhost:5433/fasalalert_test")
os.environ["BHASHINI_USER_ID"] = ""
os.environ["BHASHINI_ULCA_API_KEY"] = ""
os.environ["DATA_GOV_IN_API_KEY"] = ""
os.environ["VAPID_PUBLIC_KEY"] = ""
os.environ["VAPID_PRIVATE_KEY"] = ""
# The Ask model is an external service: tests never call it (tests that need it replace chat_completion).
os.environ["GROQ_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, configure_engine, get_engine
from app.services.notify.channels import dev_outbox_path

get_settings.cache_clear()
configure_engine(os.environ["DATABASE_URL"])

KEEP = {"spatial_ref_sys", "alembic_version", "apscheduler_jobs"}


@pytest.fixture(autouse=True)
def clean_db():
    with get_engine().begin() as c:
        tables = [r[0] for r in c.execute(text("select tablename from pg_tables where schemaname='public'"))]
        wipe = [t for t in tables if t not in KEEP]
        if wipe:
            c.execute(text("TRUNCATE " + ", ".join(wipe) + " RESTART IDENTITY CASCADE"))
    p = dev_outbox_path()
    if p.exists():
        p.unlink()
    from app.security.deps import public_limiter

    public_limiter.hits.clear()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def last_otp(phone: str) -> str:
    lines = [json.loads(ln) for ln in dev_outbox_path().read_text().splitlines()]
    body = [m for m in lines if m["to"] == phone][-1]["body"]
    return body.split("#")[-1].strip()


def login(client: TestClient, phone: str = "+919876543210") -> dict:
    r = client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": last_otp(phone)})
    assert r.status_code == 200, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    return data
