"""Public board (PRD §7.1) with an injected forecast (TEST FIXTURE values, no network)."""
from datetime import datetime, timedelta

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.core.timeutil import IST, now_ist
from app.models.tables import District
from app.services.decision import public_board as pb
from app.services.models import phenology
from app.services.models.frost_interface import FrostPrediction


def _forecast(tmax: list[float], jma_tmax: list[float] | None = None) -> dict:
    days = [(now_ist().date() + timedelta(days=i)).isoformat() for i in range(3)]
    hourly_t, hourly_v = [], []
    for d in days:
        for h in range(24):
            hourly_t.append(f"{d}T{h:02d}:00")
            hourly_v.append(20.0 + (10.0 if h == 14 else 0.0) - (5.0 if h == 5 else 0.0))
    det = {"daily": {"time": days, "temperature_2m_min": [20.0] * 3, "temperature_2m_max": tmax},
           "hourly": {"time": hourly_t, "temperature_2m": hourly_v}, "elevation": 300.0}
    jma = {"daily": {"time": days, "temperature_2m_min": [21.0] * 3, "temperature_2m_max": jma_tmax}} if jma_tmax else None
    return {"det": det, "ens": None, "jma": jma, "elevation": 300.0}


@pytest.fixture
def district(db):
    d = District(code="MH-TEST", name_en="Testpur", name_mr="टेस्टपूर", name_hi="टेस्टपुर", centroid=from_shape(Point(77.0, 20.7), srid=4326))
    db.add(d)
    db.commit()
    return d


@pytest.fixture
def cotton_mid_season(monkeypatch):
    st = phenology.StageResult("mid_season", {"en": "Flowering and boll development", "mr": "फुले", "hi": "फूल"}, None, "calendar_days",
                               None, None, None, None, None, [], {}, [])
    monkeypatch.setattr(pb, "crop_stages_for_point", lambda db, lat, lon, today: {"cotton": st})
    assert phenology.stage_thresholds("cotton", "mid_season").get("heat_c") == 43


def _capture(monkeypatch, point: float, prob: float) -> list:
    seen = []

    def fake(f):
        seen.append(f)
        if f.kind == "frost":   # cotton also has a -1 °C frost threshold; keep it far from risk
            return FrostPrediction(0.0, 20.0, 19.0, 21.0, "model", "frost-test", True)
        return FrostPrediction(prob, point, point - 1, point + 1, "model", "frost-test", True)
    monkeypatch.setattr(pb, "_predict", fake)
    return seen


def test_reason_says_below_when_estimate_is_below_threshold(db, district, cotton_mid_season, monkeypatch):
    """Found live on 2026-11-02: 'estimated 31.7 °C, above the 43 °C threshold' for every district."""
    monkeypatch.setattr(pb, "_multi_forecast", lambda pts: [_forecast([33.0, 32.0, 31.0])])
    _capture(monkeypatch, 31.7, 0.001)
    row = pb.compute_board(db)[0]
    assert row["level"] == "none" and row["kind"] == "heatwave"
    assert "below the 43 °C" in row["reason"]["en"] and "above" not in row["reason"]["en"]
    assert "पेक्षा कमी" in row["reason"]["mr"] and "से कम" in row["reason"]["hi"]
    assert "estimated 31.7 °C" in row["reason"]["en"]


def test_reason_says_above_when_estimate_crosses(db, district, cotton_mid_season, monkeypatch):
    monkeypatch.setattr(pb, "_multi_forecast", lambda pts: [_forecast([44.0, 45.0, 44.0])])
    _capture(monkeypatch, 44.6, 0.8)
    row = pb.compute_board(db)[0]
    assert row["level"] != "none"
    assert "above the 43 °C" in row["reason"]["en"]


def test_board_feeds_jma_and_skips_past_event_hours(db, district, cotton_mid_season, monkeypatch):
    monkeypatch.setattr(pb, "_multi_forecast", lambda pts: [_forecast([33.0, 32.0, 31.0], jma_tmax=[35.0, 34.0, 36.0])])
    seen = _capture(monkeypatch, 33.0, 0.001)
    pb.compute_board(db)
    heat = [f for f in seen if f.kind == "heat"]
    assert heat and all(f.lead_hours >= 0 for f in heat)
    assert heat[0].forecast_c in (35.0, 34.0, 36.0)     # JMA value, not best_match
    cutoff = datetime.now(IST)
    assert all(datetime.combine(f.valid_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=14) > cutoff for f in heat)


def test_when_words_match_the_event_kind():
    today_14 = datetime.combine(now_ist().date(), datetime.min.time(), tzinfo=IST) + timedelta(hours=14)
    tomorrow_05 = datetime.combine(now_ist().date() + timedelta(days=1), datetime.min.time(), tzinfo=IST) + timedelta(hours=5)
    assert pb._when(today_14, "en", "heatwave") == "today"          # was "tonight" for an afternoon heat peak
    assert pb._when(tomorrow_05, "en", "frost") == "tonight"
    assert pb._when(tomorrow_05 + timedelta(days=1), "en", "frost").startswith("on ")
