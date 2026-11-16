"""PRD §12 auth controls and §13 envelope."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.models.tables import OtpCode
from tests.conftest import last_otp, login

PHONE = "+919876543210"


def test_otp_happy_path_creates_user_and_tokens(client):
    data = login(client, PHONE)
    assert data["is_new_user"] is True and data["has_fields"] is False
    assert data["user"]["phone_masked"].startswith("+91 98") and "543210" not in data["user"]["phone_masked"]
    me = client.get("/api/v1/users/me", headers=data["headers"])
    assert me.status_code == 200 and me.json()["preferences"]["channels"]["sms"] is True


def test_otp_is_stored_hashed_and_not_in_logs(client, db, caplog):
    client.post("/api/v1/auth/otp/request", json={"phone": PHONE})
    code = last_otp(PHONE)
    row = db.query(OtpCode).one()
    assert code not in row.code_hash and len(row.code_hash) == 64
    assert code not in caplog.text


def test_invalid_phone_is_validation_error_envelope(client):
    r = client.post("/api/v1/auth/otp/request", json={"phone": "12345"})
    assert r.status_code == 400
    e = r.json()["error"]
    assert e["code"] == "validation_error" and e["details"]["field"] == "phone" and e["trace_id"]


def test_resend_rate_limit_60s_and_retry_after(client):
    assert client.post("/api/v1/auth/otp/request", json={"phone": PHONE}).status_code == 200
    r = client.post("/api/v1/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 429 and 0 < r.json()["error"]["details"]["retry_after"] <= 61


def test_three_sends_per_hour(client, db):
    for _ in range(3):
        assert client.post("/api/v1/auth/otp/request", json={"phone": PHONE}).status_code == 200
        db.execute(update(OtpCode).values(created_at=OtpCode.created_at - timedelta(seconds=70)))
        db.commit()
    r = client.post("/api/v1/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 429


def test_wrong_code_counts_down_then_locks(client):
    client.post("/api/v1/auth/otp/request", json={"phone": PHONE})
    good = last_otp(PHONE)
    bad = "000000" if good != "000000" else "111111"
    lefts = []
    for _ in range(5):
        r = client.post("/api/v1/auth/otp/verify", json={"phone": PHONE, "code": bad})
        lefts.append(r.json()["error"]["details"].get("attempts_left"))
    assert lefts == [4, 3, 2, 1, 0]
    r = client.post("/api/v1/auth/otp/verify", json={"phone": PHONE, "code": good})
    assert r.status_code == 429 and r.json()["error"]["details"]["reason"] == "locked"


def test_expired_code(client, db):
    client.post("/api/v1/auth/otp/request", json={"phone": PHONE})
    db.execute(update(OtpCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    r = client.post("/api/v1/auth/otp/verify", json={"phone": PHONE, "code": last_otp(PHONE)})
    assert r.status_code == 400 and r.json()["error"]["details"]["reason"] == "expired"


def test_refresh_rotation_and_reuse_detection(client):
    data = login(client, PHONE)
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()["refresh_token"]
    # reusing the old (rotated) token revokes the whole family
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r2.status_code == 401
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new})
    assert r3.status_code == 401


def test_logout_revokes_refresh(client):
    data = login(client, PHONE)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_protected_route_requires_bearer(client):
    r = client.get("/api/v1/fields")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    r = client.get("/api/v1/fields", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_production_refuses_default_secrets(monkeypatch):
    import pytest

    from app.core.config import Settings

    s = Settings(app_env="production", jwt_secret="change-me-dev-only", otp_pepper="x" * 40, sms_provider="twilio")
    with pytest.raises(RuntimeError):
        s.validate_for_startup()
