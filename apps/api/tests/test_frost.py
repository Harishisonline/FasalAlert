"""Frost and heat classifier (PRD §9.1): rule fallback, probability direction, band, heat direction.

The "model" cases run against the shipped artifact and are skipped when it has not been trained.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.services.models import frost
from app.services.models.frost_interface import FrostFeatures, FrostPrediction

HAS_ARTIFACT = frost.DEFAULT_ARTIFACT.exists()
MODES = ["rule", pytest.param("model", marks=pytest.mark.skipif(not HAS_ARTIFACT, reason="artifact not trained"))]

# Baramati block, mid January (frost) and late April (heat)
LAT, LON = 18.15, 74.58


@pytest.fixture
def mode(request, monkeypatch, tmp_path):
    if request.param == "rule":
        monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(tmp_path / "missing" / "model.joblib"))
    else:
        monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(frost.DEFAULT_ARTIFACT))
    frost.reset_cache()
    yield request.param
    frost.reset_cache()


def feats(kind: str, forecast: float, threshold: float, lead_hours: int = 48, **kw) -> FrostFeatures:
    valid = date(2027, 1, 15) if kind == "frost" else date(2027, 4, 25)
    return FrostFeatures(kind=kind, lat=LAT, lon=LON, valid_date=valid, lead_hours=lead_hours,
                         threshold_c=threshold, forecast_c=forecast, forecast_rain_mm=0.0,
                         antecedent_wetness=0.0, **kw)


def test_rule_fallback_without_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(tmp_path / "nope" / "model.joblib"))
    frost.reset_cache()
    p = frost.predict(feats("frost", 5.0, 4.0))
    frost.reset_cache()
    assert isinstance(p, FrostPrediction)
    assert p.method == "rule"
    assert p.calibrated is False
    assert 0.0 <= p.probability <= 1.0
    assert any("not found" in n for n in p.notes)
    assert p.model_version == frost.VERSION


def test_rule_table_is_fitted_for_every_kind_and_lead():
    for kind in ("frost", "heat"):
        for lead in frost.LEADS:
            q = frost.RULE_TABLE[kind][lead]["q"]
            assert len(q) == len(frost.PROBS)
            assert all(b >= a for a, b in zip(q, q[1:], strict=False))
            assert len(frost.RULE_TABLE[kind][lead]["a"]) == len(frost.RULE_TABLE["cells"])
            assert all(b > 0 for b in frost.RULE_TABLE[kind][lead]["b"])  # monotone in the forecast


@pytest.mark.skipif(not HAS_ARTIFACT, reason="artifact not trained")
def test_embedded_rule_table_matches_artifact():
    art = frost.load_artifact(frost.DEFAULT_ARTIFACT)
    frost.reset_cache()
    assert art is not None
    for kind in ("frost", "heat"):
        for lead in frost.LEADS:
            for key in ("a", "b", "q"):
                assert list(frost.RULE_TABLE[kind][lead][key]) == list(art["rule_table"][kind][lead][key])


@pytest.mark.parametrize("mode", MODES, indirect=True)
@pytest.mark.parametrize("lead", [24, 48, 72])
def test_frost_probability_rises_as_forecast_falls_through_threshold(mode, lead):
    thr = 6.0
    forecasts = np.arange(thr + 10.0, thr - 6.01, -0.5)  # warm, approaching, crossing, well below
    probs = [frost.predict(feats("frost", float(f), thr, lead)).probability for f in forecasts]
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:], strict=False)), probs
    assert probs[0] < 0.05
    # The fitted forecast-to-observed slope is well below 1 (JMA overdoes cold extremes against the
    # smoothed 1 degree IMD grid), so a forecast far below the threshold is not a certain event.
    assert probs[-1] - probs[0] > 0.2
    p_above = frost.predict(feats("frost", thr + 1.0, thr, lead)).probability
    p_below = frost.predict(feats("frost", thr - 1.0, thr, lead)).probability
    assert p_below > p_above


@pytest.mark.parametrize("mode", MODES, indirect=True)
def test_frost_probability_rises_with_threshold(mode):
    probs = [frost.predict(feats("frost", 9.0, t)).probability for t in (4.0, 6.0, 8.0, 10.0, 12.0)]
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:], strict=False)), probs
    assert probs[-1] > probs[0]


@pytest.mark.parametrize("mode", MODES, indirect=True)
def test_heat_direction(mode):
    thr = 40.0
    forecasts = np.arange(thr - 8.0, thr + 5.01, 0.5)
    probs = [frost.predict(feats("heat", float(f), thr)).probability for f in forecasts]
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:], strict=False)), probs
    assert probs[0] < 0.05
    assert probs[-1] - probs[0] > 0.2
    # a hotter threshold is less likely to be exceeded
    p38 = frost.predict(feats("heat", 39.0, 38.0)).probability
    p42 = frost.predict(feats("heat", 39.0, 42.0)).probability
    assert p38 > p42


@pytest.mark.parametrize("mode", MODES, indirect=True)
@pytest.mark.parametrize("kind,forecast,thr", [("frost", 7.0, 6.0), ("frost", 12.0, 4.0), ("heat", 41.0, 40.0),
                                               ("heat", 36.0, 42.0)])
@pytest.mark.parametrize("lead", [24, 48, 72])
def test_band_contains_point(mode, kind, forecast, thr, lead):
    p = frost.predict(feats(kind, forecast, thr, lead))
    assert p.band_low_c is not None and p.band_high_c is not None
    assert p.band_low_c <= p.point_c <= p.band_high_c
    assert p.band_high_c - p.band_low_c > 0.5  # an 80% band of a 1-3 day forecast is never this narrow
    assert abs(p.point_c - forecast) < 6.0


@pytest.mark.parametrize("mode", MODES, indirect=True)
def test_band_widens_with_lead(mode):
    w = []
    for lead in (24, 48, 72):
        p = frost.predict(feats("frost", 9.0, 6.0, lead))
        w.append(p.band_high_c - p.band_low_c)
    assert w[2] >= w[0] - 0.05


@pytest.mark.skipif(not HAS_ARTIFACT, reason="artifact not trained")
def test_model_path_is_used_and_labelled(monkeypatch):
    monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(frost.DEFAULT_ARTIFACT))
    frost.reset_cache()
    p = frost.predict(feats("frost", 5.0, 4.0, ensemble_spread_c=1.2, station_distance_km=14.0))
    frost.reset_cache()
    assert p.method == "model"
    assert p.calibrated is True
    assert p.model_version == frost.VERSION
    assert any("1 degree IMD cell" in n for n in p.notes)
    assert any("ensemble_spread_c not used" in n for n in p.notes)


@pytest.mark.skipif(not HAS_ARTIFACT, reason="artifact not trained")
def test_outside_region_is_flagged(monkeypatch):
    monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(frost.DEFAULT_ARTIFACT))
    frost.reset_cache()
    x = FrostFeatures(kind="frost", lat=28.6, lon=77.2, valid_date=date(2027, 1, 10), lead_hours=48,
                      threshold_c=4.0, forecast_c=5.0)
    p = frost.predict(x)
    frost.reset_cache()
    assert 0.0 <= p.probability <= 1.0
    assert any("outside the Maharashtra training region" in n for n in p.notes)


def test_corrupt_artifact_falls_back_to_rule(monkeypatch, tmp_path):
    bad = tmp_path / "model.joblib"
    bad.write_bytes(b"not a joblib file")
    monkeypatch.setenv("FASALALERT_FROST_ARTIFACT", str(bad))
    frost.reset_cache()
    p = frost.predict(feats("heat", 41.0, 40.0))
    frost.reset_cache()
    assert p.method == "rule"
    assert 0.0 <= p.probability <= 1.0


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        frost.predict(feats("frost", float("nan"), 4.0))
    with pytest.raises(ValueError):
        frost.predict(FrostFeatures(kind="hail", lat=LAT, lon=LON, valid_date=date(2027, 1, 1),  # type: ignore[arg-type]
                                    lead_hours=24, threshold_c=4.0, forecast_c=5.0))
