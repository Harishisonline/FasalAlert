"""Alert dedupe, quiet hours, honest delivery status (PRD §7.6)."""
from datetime import datetime, time

from app.core.timeutil import IST, today_ist
from app.models.tables import AlertDelivery, AlertRow, DecisionRow, Field, User, UserPreferences
from app.services.notify import alerts as al
from tests.conftest import login


def _setup(db, quiet=None):
    u = User(phone="+919876543210", preferred_locale="mr")
    db.add(u)
    db.flush()
    db.add(UserPreferences(user_id=u.id, channels={"sms": True, "push": False, "whatsapp": False},
                           quiet_hours_start=quiet[0] if quiet else None, quiet_hours_end=quiet[1] if quiet else None))
    f = Field(user_id=u.id, name="Mango field 1", crop="mango", lat=18.15, lon=74.58)
    db.add(f)
    db.flush()
    payload = {"headline": "Frost risk HIGH", "action_text": "Act by 21:30.", "abstain_reason": None, "action_by": None, "advisory": None,
               "risks": [{"kind": "frost", "level": "high", "probability": 0.7, "evidence": {"event_date": "2026-01-18"}}],
               "_i18n": {"headline": {"mr": "दंव धोका जास्त"}, "action_text": {"mr": "रात्री 9:30 पूर्वी उपाय करा."}}}
    row = DecisionRow(field_id=f.id, decision_date=today_ist(), headline="h", action_text="a", payload=payload)
    db.add(row)
    db.commit()
    return u, f, row


def test_alert_created_once_per_event(db):
    _, f, row = _setup(db)
    assert len(al.create_alerts_for_decision(db, f, row)) == 1
    assert len(al.create_alerts_for_decision(db, f, row)) == 0      # recompute does not re-send
    db.commit()
    a = db.query(AlertRow).one()
    assert "दंव" in a.message and a.channel == "sms"


def test_quiet_hours_window_crossing_midnight():
    prefs = UserPreferences(quiet_hours_start=time(22, 0), quiet_hours_end=time(6, 0))
    late = datetime(2026, 1, 17, 23, 30, tzinfo=IST)
    early = datetime(2026, 1, 18, 5, 0, tzinfo=IST)
    noon = datetime(2026, 1, 18, 12, 0, tzinfo=IST)
    assert al.in_quiet_hours(prefs, late) == datetime(2026, 1, 18, 6, 0, tzinfo=IST)
    assert al.in_quiet_hours(prefs, early) == datetime(2026, 1, 18, 6, 0, tzinfo=IST)
    assert al.in_quiet_hours(prefs, noon) is None


def test_dispatch_marks_sent_only_with_a_provider(db, monkeypatch):
    _, f, row = _setup(db)
    al.create_alerts_for_decision(db, f, row)
    db.commit()
    stats = al.dispatch_pending(db)          # dev_outbox provider in tests
    db.commit()
    assert stats["sent"] == 1
    assert db.query(AlertRow).one().sent_at is not None
    monkeypatch.setenv("SMS_PROVIDER", "none")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        row2 = DecisionRow(field_id=f.id, decision_date=today_ist().replace(day=1) if today_ist().day != 1 else today_ist().replace(day=2),
                           headline="h", action_text="a", payload={**row.payload, "risks": [{**row.payload["risks"][0], "evidence": {"event_date": "2026-02-01"}}]})
        db.add(row2)
        db.commit()
        al.create_alerts_for_decision(db, f, row2)
        db.commit()
        stats = al.dispatch_pending(db)
        db.commit()
        assert stats["failed"] == 1 and stats["sent"] == 0
        assert db.query(AlertDelivery).filter(AlertDelivery.status == "failed").count() == 1
    finally:
        monkeypatch.setenv("SMS_PROVIDER", "dev_outbox")
        get_settings.cache_clear()


def test_alerts_api_read_and_feedback(client, db):
    me = login(client)
    a = AlertRow(user_id=me["user"]["id"], kind="frost", level="high", message="m", channel="sms")
    db.add(a)
    db.commit()
    r = client.get("/api/v1/alerts", headers=me["headers"]).json()
    assert r["unread"] == 1
    assert client.post(f"/api/v1/alerts/{a.id}/read", headers=me["headers"]).json()["read_at"]
    assert client.get("/api/v1/alerts", headers=me["headers"]).json()["unread"] == 0
    assert client.post(f"/api/v1/alerts/{a.id}/feedback", json={"value": -1}, headers=me["headers"]).json()["feedback"] == -1
    other = login(client, "+919812345678")
    assert client.post(f"/api/v1/alerts/{a.id}/read", headers=other["headers"]).status_code == 404
