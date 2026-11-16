"""Price pipeline mechanics on a SYNTHETIC TEST-ONLY series (never stored as serving data)."""
import numpy as np
import pandas as pd

from app.services.models import price


def synthetic_frame(days=400, noise=40.0, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days, freq="D")
    t = np.arange(days)
    modal = 4000 + 400 * np.sin(2 * np.pi * t / 365) + rng.normal(0, noise, days).cumsum() * 0.1
    s = pd.DataFrame({"modal": modal, "min": modal - 200, "max": modal + 200, "arrival": 800 + rng.normal(0, 50, days),
                      "source": "test_fixture"}, index=idx)
    s.loc[s.index[::11], "modal"] = np.nan   # market holidays: gaps, never zeros
    return s


def test_frame_keeps_gaps_and_builds_features():
    f = price.make_frame(synthetic_frame())
    assert f["target_base"].isna().sum() > 0
    assert set(price.FEATURES) - {"h"} <= set(f.columns)


def test_backtest_reports_all_metrics_and_gate_is_boolean():
    bt = price.backtest(price.make_frame(synthetic_frame()), n_weeks=10)
    s = bt.summary()
    for k in ("mae_model", "mae_baseline", "rmse_model", "pinball_p10", "pinball_p50", "pinball_p90", "directional_accuracy",
              "beats_baseline_pct", "coverage_80"):
        assert k in s
    assert isinstance(bt.gate(), bool)


def test_seasonal_naive_uses_last_year_when_available():
    s = synthetic_frame()["modal"]
    v, kind = price.seasonal_naive(s, s.index[-10], 3)
    assert kind == "seasonal_naive_last_year" and v is not None
    v2, kind2 = price.seasonal_naive(s.iloc[:100], s.index[50], 3)
    assert kind2 == "naive_last_value"


def test_training_excludes_synthetic_seed(db):
    from app.models.tables import MandiMarket, MandiPrice

    m = MandiMarket(name="Pune", commodity="Mango")
    db.add(m)
    db.flush()
    db.add(MandiPrice(market_id=m.id, commodity="Mango", price_date=pd.Timestamp("2026-01-01").date(), modal_rs_qtl=4500, source="synthetic_seed"))
    db.commit()
    assert price.load_series(db, "Mango", "Pune").empty
    assert not price.load_series(db, "Mango", "Pune", allow_synthetic=True).empty
    assert price.train_series(db, "Mango", "Pune")["status"] == "no_history"
