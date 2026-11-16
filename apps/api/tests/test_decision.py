"""Decision engine: PRD AC 8, 9, 10, 12 with an injected forecast (TEST FIXTURE values, no network)."""
from datetime import date, datetime, timedelta

import pytest

from app.core.timeutil import IST, now_utc, today_ist
from app.models.tables import Field, User
from app.routers.fields import PRD_ABSTAIN_KEYS, PRD_DECISION_KEYS, PRD_RISK_KEYS, prd_shape
from app.services.decision import context as ctx
from app.services.decision import engine
from app.services.foundry.openmeteo import DayForecast, ForecastBundle
from app.services.models.frost_interface import FrostPrediction
from app.services.rag.retrieve import Hit


def bundle(tmin: float, fetched_ago_h: float = 0.5) -> ForecastBundle:
    t0 = today_ist()
    days = []
    for i in range(7):
        d = t0 + timedelta(days=i)
        days.append(DayForecast(d, tmin if i == 1 else tmin + 8, 30.0, 0.0, 0, tmin_at=datetime.combine(d, datetime.min.time(), tzinfo=IST) + timedelta(hours=5, minutes=40),
                                tmax_at=datetime.combine(d, datetime.min.time(), tzinfo=IST) + timedelta(hours=14),
                                tmin_spread_c=0.4, tmin_p10=tmin - 0.4, tmin_p90=tmin + 0.4, members=51, rain_p_heavy=0.0))
    return ForecastBundle(18.15, 74.58, 618.0, now_utc() - timedelta(hours=fetched_ago_h), days,
                          past_days=[DayForecast(t0 - timedelta(days=i), 12.0, 29.0, 0.0, 0) for i in range(3, 0, -1)],
                          source_url="https://api.open-meteo.com/v1/forecast", ensemble_model="ecmwf_ifs025")


def fake_predict(f):
    p = 0.9 if f.forecast_c < f.threshold_c else 0.02
    return FrostPrediction(p, f.forecast_c, f.forecast_c - 0.4, f.forecast_c + 0.4, "model", "frost-test", True)


ADVICE = Hit(1, "doc-1", "ICAR-CISH", "Frost protection in mango", 2019, "https://example.org/frost.pdf", "x", "en", "mango", None,
             ["frost_protection"], "Light irrigation of the basin before a cold night keeps the soil warm and protects mango flowers from frost.",
             3, similarity=0.81, score=0.05)


@pytest.fixture
def mango_field(db):
    u = User(phone="+919876543210")
    db.add(u)
    db.flush()
    f = Field(user_id=u.id, name="Mango field 1", crop="mango", lat=18.15, lon=74.58, sowing_date=today_ist() - timedelta(days=10))
    db.add(f)
    db.commit()
    return f


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(engine, "_predict", fake_predict)
    monkeypatch.setattr(engine, "transport_risk", lambda db, f, days=7, store=True: ctx.TransportResult(False, "route_unknown"))
    monkeypatch.setattr(engine, "market_summary", lambda db, f, p: None)


def test_frost_decision_matches_prd_shape_exactly(db, mango_field, monkeypatch):
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    d = engine.compute(db, mango_field)
    assert d["abstain_reason"] is None
    out = prd_shape(d, "en")
    assert list(out.keys()) == PRD_DECISION_KEYS                       # AC 12: exact keys, PRD order
    frost = next(r for r in out["risks"] if r["kind"] == "frost")
    assert set(frost) <= set(PRD_RISK_KEYS)
    assert frost["probability"] == 0.9 and frost["threshold_c"] == 4.4
    assert frost["band_low_c"] < frost["tmin_c"] < frost["band_high_c"]   # AC 8: probability, band, action time, source
    assert out["action_by"] and out["sources"] and out["advisory"]["verified"] is True
    assert out["confidence"] == frost["probability"]                   # no multiplied confidences
    assert "ICAR-CISH" in out["advisory"]["source"]
    act_by = datetime.fromisoformat(out["action_by"])
    event = datetime.fromisoformat(frost["evidence"]["event_at"])
    assert act_by < event
    mr = prd_shape(d, "mr")
    assert mr["headline"] != out["headline"] and "°C" in mr["headline"]


def test_missing_sowing_date_abstains(db, mango_field):   # AC 9
    mango_field.sowing_date = None
    db.commit()
    d = engine.compute(db, mango_field)
    assert d["abstain_reason"] == "missing_field_input"
    assert list(prd_shape(d, "en").keys()) == PRD_ABSTAIN_KEYS
    assert d["kvk"]["phone"]


def test_no_verified_advisory_abstains_with_contact(db, mango_field, monkeypatch):   # AC 10 (decision path)
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: None)
    d = engine.compute(db, mango_field)
    assert d["abstain_reason"] == "no_retrieval_above_threshold"
    assert d["kvk"]["phone"] == "1800-180-1551"          # verified fallback when no district KVK is known
    assert d["risks"]                                     # raw model output is still shown


def test_stale_forecast_abstains(db, mango_field, monkeypatch):
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2, fetched_ago_h=5))
    d = engine.compute(db, mango_field)
    assert d["abstain_reason"] == "data_stale" and d["last_update"]


def test_warm_night_is_no_risk(db, mango_field, monkeypatch):
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(18.0))
    d = engine.compute(db, mango_field)
    assert d["abstain_reason"] is None and d["action_by"] is None
    assert d["risks"][0]["level"] == "none"
    assert "No weather risk" in d["action_text"]


def test_decision_is_stored_with_inputs_for_reproducibility(db, mango_field, monkeypatch):
    from app.models.tables import DecisionRow

    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    engine.compute(db, mango_field)
    db.commit()
    row = db.query(DecisionRow).one()
    assert row.inputs["forecast"]["days"] and row.inputs["calibration"]["sensitivity"] == "normal"
    assert row.model_versions["frost"] == "frost-test" and row.policy_version
    assert row.decision_date == today_ist()
    _ = date


def test_event_hour_already_past_is_not_scored(db, mango_field, monkeypatch):
    """Found live at 08:13: this morning's 01:00 minimum was scored as a frost risk at lead 0 h."""
    b = bundle(3.2)
    b.days[0].tmin_c = 1.0                                              # very cold, but already happened
    b.days[0].tmin_at = b.fetched_at - timedelta(hours=7)
    seen = []
    monkeypatch.setattr(engine, "_predict", lambda f: seen.append(f) or fake_predict(f))
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: b)
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    d = engine.compute(db, mango_field)
    frost_dates = {f.valid_date for f in seen if f.kind == "frost"}
    assert b.days[0].valid_date not in frost_dates and b.days[1].valid_date in frost_dates
    assert all(f.lead_hours > 0 for f in seen)
    frost = next(r for r in d["risks"] if r["kind"] == "frost")
    assert frost["evidence"]["event_date"] == b.days[1].valid_date.isoformat()


def test_frost_model_receives_jma_forecast_when_present(db, mango_field, monkeypatch):
    b = bundle(3.2)
    for day in b.days:
        day.tmin_jma_c = (day.tmin_c or 0) + 1.5
    seen = []
    monkeypatch.setattr(engine, "_predict", lambda f: seen.append(f) or fake_predict(f))
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: b)
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    d = engine.compute(db, mango_field)
    f1 = next(f for f in seen if f.kind == "frost" and f.valid_date == b.days[1].valid_date)
    assert f1.forecast_c == pytest.approx(3.2 + 1.5)
    frost = next(r for r in d["risks"] if r["kind"] == "frost")
    assert frost["evidence"]["forecast_model"] == "jma_seamless"


def test_frost_risk_carries_skill_status_from_the_shipped_metrics(db, mango_field, monkeypatch):
    """Mango flowering frost is 4.4 °C; the shipped model saw 1 event at 4 °C (metrics.json), so it is preliminary."""
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    frost = next(r for r in engine.compute(db, mango_field)["risks"] if r["kind"] == "frost")
    assert frost["evidence"]["skill_status"] == "preliminary"
    assert frost["evidence"]["skill"]["n_events"] < 30


def test_assistant_risk_sentence_carries_the_skill_caveat(db, mango_field, monkeypatch):
    """The spoken or typed answer must say what the field page says: mango 4.4 °C frost skill is preliminary."""
    from app.services import assistant
    from app.services.voice import intents

    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)
    _, intro, _ = assistant._facts_for(db, mango_field, intents.resolve("माझ्या आंब्याला दंवाचा धोका आहे का?"), "mr")
    assert "मोहोर" in intro and "प्राथमिक अंदाज" in intro
