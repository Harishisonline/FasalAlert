"""Mandi price forecaster (PRD §9.2): LightGBM quantile regression (0.1, 0.5, 0.9) per commodity-market,
challenged by a seasonal-naive baseline and ARIMA. A forecast is served only if it beat the
seasonal-naive baseline out of sample in the most recent 8 weekly backtests (PRD §9.2 honest limit);
otherwise the API returns the historical range and says the forecast is unavailable.

Training never uses rows whose source is 'synthetic_seed' (PRD §10.1).
"""
from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.core.timeutil import now_utc
from app.models.tables import MandiMarket, MandiPrice

VERSION = "price-2026.11"
QUANTILES = (0.1, 0.5, 0.9)
HORIZON = 7
MIN_HISTORY_DAYS = 120
GATE_WEEKS = 8
ARTIFACT_DIR = DATA_DIR / "artifacts" / "price" / VERSION


def load_series(db: Session, commodity: str, market: str, allow_synthetic: bool = False) -> pd.DataFrame:
    q = (select(MandiPrice.price_date, MandiPrice.modal_rs_qtl, MandiPrice.min_rs_qtl, MandiPrice.max_rs_qtl,
                MandiPrice.arrival_qtl, MandiPrice.source)
         .join(MandiMarket, MandiMarket.id == MandiPrice.market_id)
         .where(MandiPrice.commodity == commodity, MandiMarket.name == market)
         .order_by(MandiPrice.price_date))
    rows = db.execute(q).all()
    df = pd.DataFrame(rows, columns=["date", "modal", "min", "max", "arrival", "source"])
    if not allow_synthetic:
        df = df[df["source"] != "synthetic_seed"]
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def make_frame(s: pd.DataFrame) -> pd.DataFrame:
    """Daily frame on a calendar index. Missing market days stay NaN; they are never filled with zero."""
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    f = s.reindex(idx)[["modal", "arrival"]].astype(float)
    m = f["modal"].ffill(limit=3)  # bridge short closures (holidays) for lag features only
    out = pd.DataFrame(index=idx)
    for lag in (1, 2, 3, 7, 14):
        out[f"lag{lag}"] = m.shift(lag - 1)  # lag1 = value at the origin
    out["roll7"] = m.rolling(7, min_periods=4).mean()
    out["roll14"] = m.rolling(14, min_periods=7).mean()
    out["vol7"] = m.pct_change().rolling(7, min_periods=4).std()
    arr = f["arrival"].ffill(limit=3)
    out["arrival"] = arr
    out["arrival_dev"] = arr / arr.rolling(28, min_periods=10).mean() - 1
    doy = idx.dayofyear.to_numpy()
    out["doy_sin"], out["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    out["target_base"] = f["modal"]
    return out


FEATURES = ["lag1", "lag2", "lag3", "lag7", "lag14", "roll7", "roll14", "vol7", "arrival", "arrival_dev",
            "doy_sin", "doy_cos", "h"]


def supervised(frame: pd.DataFrame) -> pd.DataFrame:
    """Direct multi-horizon rows: features at origin t, target = log(modal[t+h] / modal[t])."""
    parts = []
    for h in range(1, HORIZON + 1):
        part = frame.copy()
        part["h"] = h
        part["y"] = np.log(frame["target_base"].shift(-h) / frame["lag1"])
        part["origin"] = frame.index
        parts.append(part)
    df = pd.concat(parts)
    return df.dropna(subset=["lag1", "lag7", "roll7"])


def _fit(train: pd.DataFrame) -> dict[float, Any]:
    import lightgbm as lgb

    models = {}
    t = train.dropna(subset=["y"])
    for q in QUANTILES:
        m = lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=250, learning_rate=0.05, num_leaves=15,
                              min_child_samples=10, subsample=0.9, colsample_bytree=0.9, verbose=-1)
        m.fit(t[FEATURES], t["y"])
        models[q] = m
    return models


def _predict(models: dict[float, Any], rows: pd.DataFrame) -> pd.DataFrame:
    base = rows["lag1"].to_numpy()
    out = pd.DataFrame(index=rows.index)
    preds = np.vstack([models[q].predict(rows[FEATURES]) for q in QUANTILES]).T
    preds.sort(axis=1)  # no quantile crossing
    for j, q in enumerate(QUANTILES):
        out[f"p{int(q * 100)}"] = base * np.exp(preds[:, j])
    return out


def seasonal_naive(series: pd.Series, origin: pd.Timestamp, h: int) -> tuple[float | None, str]:
    """Same calendar day last year when a year of history exists (PRD glossary), else today's price."""
    ly = origin + pd.Timedelta(days=h) - pd.Timedelta(days=364)
    window = series.loc[ly - pd.Timedelta(days=3): ly + pd.Timedelta(days=3)].dropna()
    if len(window):
        return float(window.mean()), "seasonal_naive_last_year"
    v = series.loc[:origin].dropna()
    return (float(v.iloc[-1]), "naive_last_value") if len(v) else (None, "none")


def _pinball(y: float, q_pred: float, q: float) -> float:
    d = y - q_pred
    return max(q * d, (q - 1) * d)


@dataclass
class Backtest:
    weeks: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        if not self.weeks:
            return {"n_weeks": 0}
        w = pd.DataFrame(self.weeks)
        recent = w.tail(GATE_WEEKS)
        return {
            "n_weeks": len(w),
            "mae_model": round(float(w["mae_model"].mean()), 1),
            "mae_baseline": round(float(w["mae_base"].mean()), 1),
            "rmse_model": round(float(math.sqrt((w["mse_model"]).mean())), 1),
            "rmse_baseline": round(float(math.sqrt((w["mse_base"]).mean())), 1),
            "mae_arima": round(float(w["mae_arima"].dropna().mean()), 1) if w["mae_arima"].notna().any() else None,
            "pinball_p10": round(float(w["pin10"].mean()), 2),
            "pinball_p50": round(float(w["pin50"].mean()), 2),
            "pinball_p90": round(float(w["pin90"].mean()), 2),
            "directional_accuracy": round(float(w["dir_ok"].mean()), 3),
            "beats_baseline_pct": round(100 * float((w["mae_model"] < w["mae_base"]).mean())),
            "beats_baseline_recent_pct": round(100 * float((recent["mae_model"] < recent["mae_base"]).mean())),
            "recent_mae_model": round(float(recent["mae_model"].mean()), 1),
            "recent_mae_baseline": round(float(recent["mae_base"].mean()), 1),
            "coverage_80": round(float(w["covered"].mean()), 3),
            "baseline_kinds": sorted(set(w["base_kind"])),
        }

    def gate(self) -> bool:
        s = self.summary()
        return s.get("n_weeks", 0) >= GATE_WEEKS and s["recent_mae_model"] < s["recent_mae_baseline"]


def backtest(frame: pd.DataFrame, n_weeks: int = 26, min_train_days: int = 90) -> Backtest:
    sup = supervised(frame)
    series = frame["target_base"]
    last = frame.index.max() - pd.Timedelta(days=HORIZON)
    origins = [last - pd.Timedelta(days=7 * k) for k in range(n_weeks)][::-1]
    origins = [o for o in origins if (o - frame.index.min()).days >= min_train_days and not math.isnan(series.get(o, np.nan) or np.nan)]
    bt = Backtest()
    for o in origins:
        train = sup[sup["origin"] + pd.to_timedelta(sup["h"], unit="D") <= o]
        test = sup[sup["origin"] == o]
        if len(train) < 200 or test.empty:
            continue
        models = _fit(train)
        pred = _predict(models, test)
        ys, ps, bs, pins, cov, dirs = [], [], [], {10: [], 50: [], 90: []}, [], []
        kind = "none"
        for (_, row), (_, p) in zip(test.iterrows(), pred.iterrows(), strict=False):
            target_day = o + pd.Timedelta(days=int(row["h"]))
            y = series.get(target_day)
            if y is None or (isinstance(y, float) and math.isnan(y)):
                continue
            b, kind = seasonal_naive(series, o, int(row["h"]))
            if b is None:
                continue
            ys.append(y), ps.append(p["p50"]), bs.append(b)
            for q in (10, 50, 90):
                pins[q].append(_pinball(y, p[f"p{q}"], q / 100))
            cov.append(p["p10"] <= y <= p["p90"])
            dirs.append(np.sign(p["p50"] - row["lag1"]) == np.sign(y - row["lag1"]))
        if not ys:
            continue
        ar = _arima_mae(series.loc[:o], series, o)
        e = np.array(ps) - np.array(ys)
        eb = np.array(bs) - np.array(ys)
        bt.weeks.append({"origin": o.date().isoformat(), "mae_model": float(np.abs(e).mean()), "mae_base": float(np.abs(eb).mean()),
                         "mse_model": float((e ** 2).mean()), "mse_base": float((eb ** 2).mean()), "mae_arima": ar,
                         "pin10": float(np.mean(pins[10])), "pin50": float(np.mean(pins[50])), "pin90": float(np.mean(pins[90])),
                         "covered": float(np.mean(cov)), "dir_ok": float(np.mean(dirs)), "base_kind": kind})
    return bt


def _arima_mae(train: pd.Series, full: pd.Series, origin: pd.Timestamp) -> float | None:
    y = train.dropna()
    if len(y) < 60:
        return None
    try:
        from statsmodels.tsa.arima.model import ARIMA

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = ARIMA(y.asfreq("D").interpolate(limit=3).dropna().to_numpy(), order=(1, 1, 1)).fit().forecast(HORIZON)
        errs = [abs(fc[h - 1] - full[origin + pd.Timedelta(days=h)]) for h in range(1, HORIZON + 1)
                if origin + pd.Timedelta(days=h) in full.index and not math.isnan(full[origin + pd.Timedelta(days=h)])]
        return float(np.mean(errs)) if errs else None
    except Exception:  # noqa: BLE001 - ARIMA is a challenger only; a failed fit is recorded as None
        return None


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower())


def artifact_path(commodity: str, market: str) -> Path:
    return ARTIFACT_DIR / f"{_slug(commodity)}__{_slug(market)}.joblib"


def train_series(db: Session, commodity: str, market: str) -> dict[str, Any]:
    s = load_series(db, commodity, market)
    if s.empty:
        return {"commodity": commodity, "market": market, "status": "no_history"}
    frame = make_frame(s)
    observed = int(frame["target_base"].notna().sum())
    if observed < MIN_HISTORY_DAYS:
        return {"commodity": commodity, "market": market, "status": "cold_start", "observed_days": observed}
    bt = backtest(frame)
    summary = bt.summary()
    status = "serving" if bt.gate() else "not_beating_baseline"
    out = {"commodity": commodity, "market": market, "status": status, "observed_days": observed,
           "from": s.index.min().date().isoformat(), "to": s.index.max().date().isoformat(), **summary}
    if status == "serving":
        models = _fit(supervised(frame))
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"models": models, "trained_at": now_utc().isoformat(), "summary": out}, artifact_path(commodity, market))
    return out


@dataclass
class PriceForecast:
    available: bool
    reason: str | None
    points: list[dict[str, Any]]
    beats_baseline_pct: int | None
    historical_range: dict[str, Any] | None
    trained_at: str | None
    model_version: str | None


def historical_range(s: pd.DataFrame) -> dict[str, Any] | None:
    if s.empty:
        return None
    last = s.index.max()
    win = s.loc[last - pd.Timedelta(days=90):, "modal"].dropna()
    # Same season in earlier years when available: +-30 days around today's day of year.
    seasonal = s[(abs(s.index.dayofyear - last.dayofyear) <= 30) & (s.index < last - pd.Timedelta(days=300))]["modal"].dropna()
    use = seasonal if len(seasonal) >= 20 else win
    if use.empty:
        return None
    return {"low": float(use.quantile(0.1)), "high": float(use.quantile(0.9)),
            "from": use.index.min().date().isoformat(), "to": use.index.max().date().isoformat()}


def forecast(db: Session, commodity: str, market: str, days: int = HORIZON) -> PriceForecast:
    s = load_series(db, commodity, market)
    rng = historical_range(s)
    if s.empty:
        return PriceForecast(False, "no_history", [], None, None, None, None)
    path = artifact_path(commodity, market)
    if not path.exists():
        observed = int(s["modal"].notna().sum())
        reason = "cold_start" if observed < MIN_HISTORY_DAYS else "not_beating_baseline"
        meta = _status_note(commodity, market)
        if meta:
            reason = meta.get("status", reason) if meta.get("status") != "serving" else "model_missing"
        return PriceForecast(False, reason, [], meta.get("beats_baseline_pct") if meta else None, rng, None, None)
    art = joblib.load(path)
    frame = make_frame(s)
    origin = frame.index.max()
    row = frame.loc[[origin]].copy()
    rows = pd.concat([row.assign(h=h) for h in range(1, min(days, HORIZON) + 1)])
    pred = _predict(art["models"], rows)
    pts = [{"date": (origin + pd.Timedelta(days=h)).date().isoformat(), "p10": round(float(p["p10"])),
            "p50": round(float(p["p50"])), "p90": round(float(p["p90"]))} for h, (_, p) in enumerate(pred.iterrows(), 1)]
    return PriceForecast(True, None, pts, art["summary"].get("beats_baseline_pct"), rng, art["trained_at"], VERSION)


def _status_note(commodity: str, market: str) -> dict[str, Any] | None:
    p = ARTIFACT_DIR / "training_status.json"
    if not p.exists():
        return None
    for r in json.loads(p.read_text()).get("series", []):
        if r["commodity"] == commodity and r["market"] == market:
            return r
    return None


def summarize_recent(s: pd.DataFrame) -> dict[str, Any]:
    if s.empty:
        return {}
    last_date = s.index.max()
    last = s.loc[last_date]
    med5 = s.loc[last_date - pd.Timedelta(days=6):, "modal"].dropna().tail(5).median()
    wk = s.loc[: last_date - pd.Timedelta(days=7), "modal"].dropna()
    trend = (float(last["modal"]) / float(wk.iloc[-1]) - 1) * 100 if len(wk) else None
    return {"modal_rs_qtl": float(last["modal"]), "median_5d": float(med5) if not math.isnan(med5) else None,
            "arrival_qtl": None if pd.isna(last["arrival"]) else float(last["arrival"]),
            "price_date": last_date.date().isoformat(), "trend_7d_pct": round(trend, 1) if trend is not None else None,
            "source": str(last["source"])}


def last_date_of(s: pd.DataFrame) -> date | None:
    return s.index.max().date() if not s.empty else None




def train_all(db: Session) -> dict[str, Any]:
    """Train every commodity-market series with real (non-synthetic) history; write a status file that the
    API reads to explain why a forecast is unavailable, and register the run in model_registry."""
    from app.services.models.registry import register

    pairs = db.execute(select(MandiPrice.commodity, MandiMarket.name).join(MandiMarket, MandiMarket.id == MandiPrice.market_id)
                       .where(MandiPrice.source != "synthetic_seed").group_by(MandiPrice.commodity, MandiMarket.name)).all()
    results = [train_series(db, c, m) for c, m in pairs]
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    status = {"version": VERSION, "trained_at": now_utc().isoformat(), "series": results}
    (ARTIFACT_DIR / "training_status.json").write_text(json.dumps(status, indent=1))
    serving = [r for r in results if r.get("status") == "serving"]
    register(db, name="price", version=VERSION, kind="quantile_regressor",
             dataset_ref="AGMARKNET daily modal price and arrivals (data.gov.in / official exports); synthetic_seed excluded",
             metrics={"series": len(results), "serving": len(serving), "per_series": results,
                      "serving_status": "serving" if serving else "unavailable"},
             thresholds={"gate": f"recent {GATE_WEEKS} weekly backtests MAE below seasonal naive", "min_history_days": MIN_HISTORY_DAYS},
             artifact_path=str(ARTIFACT_DIR.relative_to(DATA_DIR.parent)), notes="LightGBM quantile 0.1/0.5/0.9, direct 1 to 7 day horizons")
    return {"series": len(results), "serving": len(serving)}
