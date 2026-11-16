"""Frost and heat classifier (PRD §9.1): runtime `predict`, plus the feature code shared with training.

What the model estimates
  frost: P(IMD 1 degree cell Tmin on valid_date < threshold_c)
  heat:  P(IMD 1 degree cell Tmax on valid_date > threshold_c)
given an Open-Meteo point forecast `forecast_c` issued `lead_hours` ahead. It is trained on archived
JMA GSM forecasts (Open-Meteo Previous Runs API, 2016 to 2025) against IMD gridded observations, with
IMD 1986 to 2015 as the climatology that the features are expressed against. See
docs/model_cards/frost.md and scripts/train_frost.py.

Pass a JMA forecast (Open-Meteo `models=jma_seamless`) as `forecast_c` where possible: the held-out
transfer test in the model card shows lower skill when the default `best_match` forecast is passed.

Two stages, both shipped in one artifact:
  1. ErrorModel: a forecast-error model. Observed minus forecast has a mean mu(x) (linear) and a spread
     sigma(x) (log-linear), and the standardised residual has an empirical distribution. It gives the
     point (median) and the 80% band (10th and 90th percentiles).
  2. A calibrated classifier for P(event) with the threshold as an input: logistic regression on the
     stage 1 margin plus a climatological margin, and a LightGBM challenger on raw features. Both are
     class weighted and then Platt-calibrated on held-out seasons. Training picks one per kind.

Heat is handled in "signed" space: with s = -1, Tmax > thr is the same event as (-Tmax) < (-thr), so
one code path serves both kinds.

Fallback (PRD §9.1): if the artifact is missing or fails, P(event) comes from forecast minus threshold
against the empirical error distribution for that kind, lead and nearest cell (after a per-cell
straight-line correction of the forecast), embedded below as constants. `method="rule"`,
`calibrated=False`.

Inputs the model does not use, by design (reported in `notes`):
  * ensemble_spread_c: Open-Meteo keeps ensemble history only for recent months, so no training data.
  * station_distance_km: not learnable from a gridded target.
  * elevation_m: every training point is a cell centre, so elevation would only identify cells. Field
    elevation reaches the model through the Open-Meteo forecast, which is lapse-rate downscaled to the
    requested point.
  * observed_lags_c: IMD grids are released yearly, so lags consistent with training would not exist
    at serving time. Training reports the skill they would add (ablation) but the shipped model omits them.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import API_ROOT
from app.services.models.frost_interface import FrostFeatures, FrostPrediction, Kind

log = logging.getLogger("fasalalert.models.frost")

VERSION = "frost-2026.11"
DEFAULT_ARTIFACT = API_ROOT / "data" / "artifacts" / "frost" / VERSION / "model.joblib"
SIGN: dict[str, float] = {"frost": 1.0, "heat": -1.0}
LEADS = (1, 2, 3)

# Probability levels of every stored empirical quantile table.
PROBS = np.round(np.concatenate([[0.005, 0.01, 0.025], np.arange(0.05, 0.951, 0.05), [0.975, 0.99, 0.995]]), 4)

# ---------------------------------------------------------------------------------------------
# Rule fallback table, written by scripts/train_frost.py (it warns when this copy is stale).
# Per kind and lead (days), for each training cell: a straight line from forecast to observed
# (observed = a + b * forecast, deg C, unsigned), and "q" = quantiles at PROBS of the pooled residual.
# frost: IMD 1 degree Tmin minus JMA GSM Tmin, Dec to Feb; heat: Tmax, Mar to May; 2016 to 2025.
# ---------------------------------------------------------------------------------------------
RULE_TABLE: dict[str, Any] = {
    'cells': (
        (16.5, 73.5), (16.5, 74.5), (17.5, 73.5), (17.5, 74.5), (17.5, 75.5), (17.5, 76.5), (18.5, 73.5),
        (18.5, 74.5), (18.5, 75.5), (18.5, 76.5), (18.5, 77.5), (19.5, 73.5), (19.5, 74.5), (19.5, 75.5),
        (19.5, 76.5), (19.5, 77.5), (19.5, 79.5), (19.5, 80.5), (20.5, 73.5), (20.5, 74.5), (20.5, 75.5),
        (20.5, 76.5), (20.5, 77.5), (20.5, 78.5), (20.5, 79.5), (20.5, 80.5), (21.5, 74.5), (21.5, 75.5),
        (21.5, 76.5), (21.5, 77.5), (21.5, 78.5), (21.5, 79.5), (21.5, 80.5),
    ),
    'frost': {
        1: {
            'a': (
                8.025, 8.563, 12.292, 4.326, 5.375, 1.15, 7.781, 5.759, 1.498, 2.113, 3.98, 10.791, 3.969,
                2.982, 2.231, 3.0, 4.915, 8.788, 8.695, 3.725, 0.589, 2.258, 2.836, 1.44, 3.335, 7.122,
                4.695, 1.066, 3.796, 2.705, 2.116, 2.902, 4.028,
            ),
            'b': (
                0.566, 0.503, 0.3, 0.628, 0.564, 0.79, 0.555, 0.546, 0.697, 0.76, 0.67, 0.337, 0.602, 0.661,
                0.694, 0.704, 0.657, 0.479, 0.459, 0.659, 0.805, 0.762, 0.71, 0.761, 0.679, 0.525, 0.567,
                0.791, 0.674, 0.851, 0.728, 0.65, 0.651,
            ),
            'q': (
                -4.061, -3.601, -3.004, -2.513, -1.946, -1.554, -1.267, -1.016, -0.795, -0.584, -0.384,
                -0.19, -0.006, 0.184, 0.366, 0.567, 0.786, 1.023, 1.272, 1.57, 1.944, 2.506, 3.052, 3.663,
                4.168,
            ),
        },
        2: {
            'a': (
                8.107, 8.177, 12.177, 4.064, 5.14, 1.053, 8.035, 5.758, 1.402, 2.415, 4.322, 10.726, 4.293,
                3.227, 2.626, 3.345, 5.267, 8.792, 8.81, 3.828, 1.139, 2.716, 3.306, 1.533, 3.784, 7.242,
                4.874, 1.465, 4.09, 2.91, 2.506, 3.138, 4.182,
            ),
            'b': (
                0.561, 0.523, 0.306, 0.639, 0.572, 0.787, 0.537, 0.543, 0.696, 0.734, 0.643, 0.341, 0.577,
                0.642, 0.666, 0.675, 0.625, 0.469, 0.451, 0.646, 0.765, 0.724, 0.673, 0.746, 0.642, 0.509,
                0.551, 0.755, 0.642, 0.818, 0.693, 0.627, 0.632,
            ),
            'q': (
                -4.183, -3.712, -3.102, -2.604, -1.996, -1.594, -1.281, -1.029, -0.793, -0.584, -0.38,
                -0.189, -0.001, 0.19, 0.395, 0.596, 0.822, 1.055, 1.312, 1.607, 1.968, 2.502, 3.048, 3.688,
                4.075,
            ),
        },
        3: {
            'a': (
                8.687, 8.463, 10.893, 4.928, 6.177, 2.004, 8.113, 6.955, 2.788, 3.511, 5.288, 10.301, 5.462,
                4.523, 3.648, 4.088, 6.196, 8.317, 9.527, 4.653, 2.076, 3.548, 4.185, 2.114, 4.9, 7.155,
                5.921, 2.216, 4.703, 2.944, 3.627, 4.355, 4.85,
            ),
            'b': (
                0.549, 0.519, 0.422, 0.599, 0.522, 0.736, 0.554, 0.487, 0.621, 0.669, 0.587, 0.402, 0.516,
                0.571, 0.61, 0.622, 0.579, 0.543, 0.424, 0.601, 0.722, 0.678, 0.62, 0.708, 0.573, 0.537,
                0.492, 0.721, 0.615, 0.831, 0.623, 0.558, 0.609,
            ),
            'q': (
                -4.377, -3.897, -3.196, -2.671, -2.03, -1.583, -1.274, -0.994, -0.76, -0.548, -0.351,
                -0.156, 0.023, 0.223, 0.417, 0.62, 0.826, 1.051, 1.31, 1.595, 1.958, 2.494, 2.971, 3.604,
                3.995,
            ),
        },
    },
    'heat': {
        1: {
            'a': (
                24.702, 22.274, 24.493, 21.333, 18.152, 18.956, 24.781, 19.221, 14.124, 15.929, 18.033,
                25.342, 17.418, 10.659, 10.763, 14.353, 19.107, 15.317, 21.291, 13.987, 8.15, 8.961, 9.118,
                8.878, 13.224, 13.912, 11.367, 7.471, 5.432, 8.829, 7.304, 9.569, 9.291,
            ),
            'b': (
                0.3, 0.378, 0.3, 0.429, 0.532, 0.549, 0.311, 0.483, 0.675, 0.647, 0.557, 0.3, 0.575, 0.761,
                0.757, 0.675, 0.545, 0.622, 0.418, 0.652, 0.839, 0.831, 0.807, 0.809, 0.672, 0.676, 0.698,
                0.865, 0.88, 0.887, 0.816, 0.752, 0.768,
            ),
            'q': (
                -4.902, -4.167, -3.209, -2.644, -2.035, -1.644, -1.355, -1.121, -0.897, -0.695, -0.501,
                -0.316, -0.121, 0.075, 0.274, 0.488, 0.737, 1.004, 1.291, 1.644, 2.109, 2.992, 4.133, 5.623,
                6.358,
            ),
        },
        2: {
            'a': (
                24.802, 22.599, 24.635, 21.295, 17.754, 19.291, 25.102, 19.224, 14.483, 15.69, 16.554,
                25.455, 17.522, 11.207, 11.257, 13.613, 17.222, 15.392, 21.654, 13.877, 8.342, 8.763, 9.723,
                9.037, 13.438, 14.402, 12.067, 7.968, 5.815, 9.253, 7.996, 10.993, 11.224,
            ),
            'b': (
                0.3, 0.372, 0.3, 0.43, 0.541, 0.537, 0.304, 0.483, 0.663, 0.65, 0.592, 0.3, 0.571, 0.744,
                0.74, 0.69, 0.591, 0.617, 0.409, 0.653, 0.83, 0.832, 0.786, 0.801, 0.664, 0.661, 0.678,
                0.848, 0.867, 0.87, 0.794, 0.712, 0.716,
            ),
            'q': (
                -5.38, -4.452, -3.378, -2.764, -2.122, -1.715, -1.412, -1.164, -0.938, -0.723, -0.52,
                -0.308, -0.108, 0.106, 0.328, 0.548, 0.806, 1.088, 1.388, 1.732, 2.21, 3.06, 4.127, 5.376,
                6.16,
            ),
        },
        3: {
            'a': (
                23.142, 20.387, 24.333, 17.011, 9.317, 10.045, 23.231, 14.019, 7.417, 6.4, 7.724, 25.146,
                12.274, 5.64, 5.407, 5.234, 11.984, 15.171, 20.259, 9.721, 4.677, 4.701, 5.061, 4.294,
                7.683, 12.803, 8.86, 5.311, 3.501, 8.329, 4.14, 7.7, 7.848,
            ),
            'b': (
                0.342, 0.426, 0.3, 0.54, 0.75, 0.769, 0.352, 0.611, 0.836, 0.882, 0.802, 0.3, 0.7, 0.874,
                0.875, 0.884, 0.704, 0.608, 0.44, 0.75, 0.915, 0.923, 0.889, 0.9, 0.786, 0.683, 0.747,
                0.907, 0.912, 0.881, 0.872, 0.774, 0.779,
            ),
            'q': (
                -5.083, -4.283, -3.134, -2.408, -1.802, -1.434, -1.154, -0.917, -0.71, -0.535, -0.358,
                -0.196, -0.021, 0.143, 0.322, 0.515, 0.715, 0.948, 1.202, 1.501, 1.89, 2.485, 3.027, 3.854,
                4.446,
            ),
        },
    },
}


# ---------------------------------------------------------------------------------------------
# Shared feature code (training and serving)
# ---------------------------------------------------------------------------------------------
def doy365(d: date | pd.Timestamp) -> int:
    """Day of year on a 365-day calendar (29 Feb shares 28 Feb's index)."""
    ts = pd.Timestamp(d)
    n = int(ts.day_of_year)
    if ts.is_leap_year and ts.month > 2:
        n -= 1
    return n


def doy365_series(dates: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(dates)
    n = dt.dt.day_of_year.to_numpy()
    adj = (dt.dt.is_leap_year & (dt.dt.month > 2)).to_numpy()
    return n - adj.astype(int)


def in_season(doy: int, first: int, last: int) -> bool:
    """True when doy lies in [first, last], allowing a window that wraps over 31 Dec."""
    return first <= doy <= last if first <= last else (doy >= first or doy <= last)


def lead_days_from_hours(lead_hours: float) -> int:
    return int(min(3, max(1, round(float(lead_hours) / 24.0))))


def frame_from_columns(f_s: Any, lead: Any, doy: Any, lat: Any, lon: Any, rain_f: Any, wet7: Any,
                       cm_s: Any, cs: Any, cell: Any) -> pd.DataFrame:
    """Signed-space base frame. f_s and cm_s are already multiplied by the kind's sign; `cell` is the
    index of the IMD training cell (nearest cell at serving time)."""
    df = pd.DataFrame({
        "f": np.asarray(f_s, float), "L": np.asarray(lead, float), "doy": np.asarray(doy, float),
        "j": np.asarray(cell, int),
        "lat": np.asarray(lat, float), "lon": np.asarray(lon, float),
        "rain_f": np.asarray(rain_f, float), "wet7": np.asarray(wet7, float),
        "cm": np.asarray(cm_s, float), "cs": np.asarray(cs, float),
    })
    df["rain_f"] = df["rain_f"].fillna(0.0).clip(lower=0)
    df["wet7"] = df["wet7"].fillna(0.0).clip(lower=0)
    return df


def _common(df: pd.DataFrame) -> dict[str, np.ndarray]:
    ang = 2 * np.pi * df["doy"].to_numpy() / 365.0
    L = df["L"].to_numpy()
    fa = df["f"].to_numpy() - df["cm"].to_numpy()
    return {
        "L2": (L == 2).astype(float), "L3": (L == 3).astype(float), "fa": fa,
        "sin1": np.sin(ang), "cos1": np.cos(ang),
        "lrain": np.log1p(df["rain_f"].to_numpy()), "lwet": np.log1p(df["wet7"].to_numpy()),
    }


def _cell_onehot(df: pd.DataFrame, n_cells: int) -> np.ndarray:
    """Cell fixed effects: the JMA-vs-IMD bias differs a lot between coastal, ghat and plateau cells."""
    out = np.zeros((len(df), n_cells))
    if n_cells:
        out[np.arange(len(df)), np.clip(df["j"].to_numpy(), 0, n_cells - 1)] = 1.0
    return out


def x_mu(df: pd.DataFrame, n_cells: int = 0) -> np.ndarray:
    c = _common(df)
    cols = [c["L2"], c["L3"], c["fa"], c["fa"] * c["L2"], c["fa"] * c["L3"], df["cm"].to_numpy(),
            df["cs"].to_numpy(), c["sin1"], c["cos1"], df["lat"].to_numpy(), df["lon"].to_numpy(),
            c["lrain"], c["lwet"], c["lrain"] * c["fa"]]
    return np.column_stack(cols + [_cell_onehot(df, n_cells)])


def x_sigma(df: pd.DataFrame, n_cells: int = 0) -> np.ndarray:
    c = _common(df)
    cols = [c["L2"], c["L3"], df["cs"].to_numpy(), np.abs(c["fa"]), c["lrain"], c["lwet"], c["sin1"],
            c["cos1"], df["lat"].to_numpy(), df["lon"].to_numpy()]
    return np.column_stack(cols + [_cell_onehot(df, n_cells)])


def _phi(x: np.ndarray) -> np.ndarray:
    from scipy.special import ndtr  # scipy ships with scikit-learn

    return ndtr(x)


def _tail_cdf(s: np.ndarray, zq: np.ndarray, probs: np.ndarray) -> np.ndarray:
    """Monotone CDF from empirical quantiles, with Gaussian-shaped tails beyond the stored range."""
    s = np.asarray(s, float)
    p = np.interp(s, zq, probs)
    lo, hi = s < zq[0], s > zq[-1]
    if lo.any():
        p[lo] = probs[0] * _phi(s[lo] - zq[0] - 2.0) / _phi(np.array(-2.0))
    if hi.any():
        p[hi] = 1.0 - (1.0 - probs[-1]) * _phi(-(s[hi] - zq[-1]) - 2.0) / _phi(np.array(-2.0))
    return np.clip(p, 1e-6, 1 - 1e-6)


class ErrorModel:
    """Stage 1: observed = forecast + mu(x) + sigma(x) * z, z from an empirical distribution."""

    def __init__(self, alpha: float = 1.0, n_cells: int = 0) -> None:
        self.alpha = alpha
        self.n_cells = n_cells

    def _xm(self, df: pd.DataFrame) -> np.ndarray:
        return x_mu(df, self.n_cells)

    def _xs(self, df: pd.DataFrame) -> np.ndarray:
        return x_sigma(df, self.n_cells)

    @staticmethod
    def _fit_parts(xm: np.ndarray, xs: np.ndarray, r: np.ndarray, alpha: float):
        from sklearn.linear_model import LinearRegression, Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        mu = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(xm, r)
        e = r - mu.predict(xm)
        sg = make_pipeline(StandardScaler(), LinearRegression()).fit(xs, np.log(e ** 2 + 0.05))
        scale = float(np.std(e / np.exp(0.5 * sg.predict(xs))))
        return mu, sg, scale

    def fit(self, df: pd.DataFrame, y_s: np.ndarray, groups: np.ndarray | None = None) -> ErrorModel:
        """Fit mu and sigma on all rows. With `groups` (seasons), the standardised-error distribution
        is taken from leave-one-group-out residuals, so the band reflects out-of-sample error."""
        r = np.asarray(y_s, float) - df["f"].to_numpy()
        xm, xs = self._xm(df), self._xs(df)
        self.mu_, self.sg_, self.scale_ = self._fit_parts(xm, xs, r, self.alpha)
        if groups is None or len(np.unique(groups)) < 3:
            z = (r - self.mu_.predict(xm)) / (self.scale_ * np.exp(0.5 * self.sg_.predict(xs)))
            self.oof_ = False
        else:
            z = np.empty(len(r))
            for g in np.unique(groups):
                te = groups == g
                mu, sg, scale = self._fit_parts(xm[~te], xs[~te], r[~te], self.alpha)
                z[te] = (r[te] - mu.predict(xm[te])) / (scale * np.exp(0.5 * sg.predict(xs[te])))
            self.oof_ = True
        self.zq_ = np.quantile(z, PROBS)
        self.n_ = len(z)
        return self

    def mu_sigma(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        mu = self.mu_.predict(self._xm(df))
        sg = self.scale_ * np.exp(0.5 * self.sg_.predict(self._xs(df)))
        return mu, np.clip(sg, 0.3, 10.0)

    def cdf(self, df: pd.DataFrame, thr_s: np.ndarray) -> np.ndarray:
        """P(y_s < thr_s)."""
        mu, sg = self.mu_sigma(df)
        return _tail_cdf((np.asarray(thr_s, float) - df["f"].to_numpy() - mu) / sg, self.zq_, PROBS)

    def quantile(self, df: pd.DataFrame, p: float) -> np.ndarray:
        mu, sg = self.mu_sigma(df)
        return df["f"].to_numpy() + mu + sg * float(np.interp(p, PROBS, self.zq_))


LR_FEATURES = ["g", "s", "c", "L2", "L3", "gL2", "gL3"]
GB_FEATURES = ["m", "f", "thr", "thr_cm", "cm", "cs", "L", "sin1", "cos1", "lat", "lon", "lrain", "lwet"]
GB_MONOTONE = [1, -1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
CLASSIFIER_NAMES = {"lr": "logistic regression", "gb": "LightGBM"}


def lr_design(df: pd.DataFrame, thr_s: np.ndarray, em: ErrorModel) -> np.ndarray:
    mu, sg = em.mu_sigma(df)
    thr_s = np.asarray(thr_s, float)
    s = (thr_s - df["f"].to_numpy() - mu) / sg
    p1 = _tail_cdf(s, em.zq_, PROBS)
    g = np.log(p1 / (1 - p1))
    c = (thr_s - df["cm"].to_numpy()) / df["cs"].to_numpy()
    L2 = (df["L"].to_numpy() == 2).astype(float)
    L3 = (df["L"].to_numpy() == 3).astype(float)
    return np.column_stack([g, s, np.clip(c, -8, 8), L2, L3, g * L2, g * L3])


def gb_design(df: pd.DataFrame, thr_s: np.ndarray) -> np.ndarray:
    c = _common(df)
    thr_s = np.asarray(thr_s, float)
    f = df["f"].to_numpy()
    cm = df["cm"].to_numpy()
    return np.column_stack([thr_s - f, f, thr_s, thr_s - cm, cm, df["cs"].to_numpy(), df["L"].to_numpy(),
                            c["sin1"], c["cos1"], df["lat"].to_numpy(), df["lon"].to_numpy(), c["lrain"],
                            c["lwet"]])


def classifier_proba(kind_art: dict[str, Any], which: str, df: pd.DataFrame, thr_s: np.ndarray) -> np.ndarray:
    if which == "lr":
        X = lr_design(df, thr_s, kind_art["error_model"])
    else:
        X = gb_design(df, thr_s)
    return kind_art[which].predict_proba(X)[:, 1]


# ---------------------------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------------------------
_lock = threading.Lock()
_cache: dict[str, Any] = {}


def artifact_path() -> Path:
    return Path(os.environ.get("FASALALERT_FROST_ARTIFACT", str(DEFAULT_ARTIFACT)))


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def load_artifact(path: Path | None = None) -> dict[str, Any] | None:
    """Load the artifact once (lazily). Returns None when it is missing or unreadable."""
    p = Path(path) if path is not None else artifact_path()
    key = str(p)
    with _lock:
        if key in _cache:
            return _cache[key]
        art = None
        if p.exists():
            try:
                import joblib

                art = joblib.load(p)
                if art.get("version") != VERSION:
                    log.warning("frost artifact version %s != code version %s", art.get("version"), VERSION)
            except Exception:  # corrupt or incompatible artifact: degrade to the rule
                log.exception("frost artifact at %s could not be loaded", p)
                art = None
        _cache[key] = art
        return art


# ---------------------------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------------------------
def _ignored_inputs_notes(x: FrostFeatures) -> list[str]:
    notes = []
    if x.ensemble_spread_c is not None:
        notes.append("ensemble_spread_c not used: no archived ensemble exists to train on")
    if x.station_distance_km is not None:
        notes.append("station_distance_km not used: not learnable from a 1 degree gridded target")
    if any(v is not None for v in x.observed_lags_c):
        notes.append("observed_lags_c not used by the shipped model (IMD grids are not available in real time)")
    return notes


def _check(x: FrostFeatures) -> None:
    if x.kind not in SIGN:
        raise ValueError(f"kind must be 'frost' or 'heat', got {x.kind!r}")
    for name in ("forecast_c", "threshold_c", "lead_hours"):
        v = getattr(x, name)
        if v is None or not math.isfinite(float(v)):
            raise ValueError(f"{name} must be a finite number")


def _nearest(cells: Any, lat: float, lon: float) -> tuple[int, float]:
    c = np.asarray(cells, float)  # (n, 2) lat, lon
    d = np.maximum(np.abs(c[:, 0] - lat), np.abs(c[:, 1] - lon) * math.cos(math.radians(lat)))
    i = int(np.argmin(d))
    return i, float(d[i])


def rule_predict(x: FrostFeatures, notes: list[str] | None = None) -> FrostPrediction:
    """PRD §9.1 fallback: forecast minus threshold against the empirical error distribution, after a
    per-cell straight-line correction of the forecast (nearest training cell)."""
    _check(x)
    notes = list(notes or [])
    L = lead_days_from_hours(x.lead_hours)
    if not RULE_TABLE:
        raise RuntimeError("frost.RULE_TABLE is empty; run scripts/train_frost.py and paste its table")
    ci, dist = _nearest(RULE_TABLE["cells"], x.lat, x.lon)
    tab = RULE_TABLE[x.kind][L]
    q = np.asarray(tab["q"], float)  # residual quantiles around the corrected forecast
    if dist > 1.0:
        notes.append("field is outside the Maharashtra training cells; nearest cell's error used")
    f, thr = float(x.forecast_c), float(x.threshold_c)
    fc = float(tab["a"][ci]) + float(tab["b"][ci]) * f  # corrected forecast
    # frost: observed < thr  <=>  residual < thr - corrected forecast
    p_below = float(_tail_cdf(np.array([thr - fc]), q, PROBS)[0])
    prob = p_below if x.kind == "frost" else 1.0 - p_below
    q10, q50, q90 = (fc - f + float(np.interp(p, PROBS, q)) for p in (0.1, 0.5, 0.9))
    notes.append(f"rule fallback: empirical {x.kind} forecast error at {L * 24} h lead, cell "
                 f"{RULE_TABLE['cells'][ci][0]}N {RULE_TABLE['cells'][ci][1]}E (PRD 9.1)")
    notes.extend(_ignored_inputs_notes(x))
    return FrostPrediction(
        probability=round(min(max(prob, 0.0), 1.0), 4), point_c=round(f + q50, 2),
        band_low_c=round(f + q10, 2), band_high_c=round(f + q90, 2), method="rule",
        model_version=VERSION, calibrated=False, notes=notes,
    )


def _nearest_cell(art: dict[str, Any], lat: float, lon: float) -> tuple[int, float]:
    return _nearest(art["cells"], lat, lon)


def _model_predict(art: dict[str, Any], x: FrostFeatures) -> FrostPrediction:
    kind: Kind = x.kind
    s = SIGN[kind]
    ka = art["kinds"][kind]
    notes: list[str] = []
    ci, dist = _nearest_cell(art, x.lat, x.lon)
    clat, clon = art["cells"][ci]
    if dist > 1.0:
        notes.append(f"field is {dist:.1f} deg from the nearest training cell ({clat}N {clon}E): outside the "
                     "Maharashtra training region")
    notes.append(f"1 degree IMD cell {clat}N {clon}E: cannot resolve frost pockets or slopes inside the cell")
    L = lead_days_from_hours(x.lead_hours)
    if x.lead_hours < 12 or x.lead_hours > 84:
        notes.append(f"lead {x.lead_hours} h outside the trained 24 to 72 h leads; using the {L * 24} h model")
    doy = doy365(x.valid_date)
    if not in_season(doy, *ka["season_doys"]):
        notes.append(f"{x.valid_date} is outside the {kind} training season; result is an extrapolation")
    clim = art["clim"][kind]  # (ncells, 366, 2) unsigned mean, std; index doy 1..365
    cm, cs = float(clim[ci, doy, 0]), float(clim[ci, doy, 1])
    lo_thr, hi_thr = ka["threshold_range"]
    if not lo_thr <= x.threshold_c <= hi_thr:
        notes.append(f"threshold {x.threshold_c} C outside the trained range {lo_thr} to {hi_thr} C")
    if x.forecast_rain_mm is None:
        notes.append("forecast_rain_mm missing: taken as 0 mm")
    if x.antecedent_wetness is None:
        notes.append("antecedent_wetness missing: taken as 0 mm")
    elev_ref = art.get("cell_elevation_m", [None] * len(art["cells"]))[ci]
    if x.elevation_m is not None and elev_ref is not None and abs(x.elevation_m - elev_ref) > 300:
        notes.append(f"field elevation {x.elevation_m:.0f} m differs from the cell reference {elev_ref:.0f} m by "
                     "more than 300 m; only the forecast's own lapse-rate downscaling accounts for it")
    df = frame_from_columns([s * x.forecast_c], [L], [doy], [clat], [clon], [x.forecast_rain_mm],
                            [x.antecedent_wetness], [s * cm], [cs], [ci])
    em: ErrorModel = ka["error_model"]
    qs = {p: float(em.quantile(df, p)[0]) * s for p in (0.1, 0.5, 0.9)}
    band_low, band_high = min(qs[0.1], qs[0.9]), max(qs[0.1], qs[0.9])
    shipped = ka["shipped"]
    prob = float(classifier_proba(ka, shipped, df, np.array([s * x.threshold_c]))[0])
    notes.append(f"{CLASSIFIER_NAMES.get(shipped, shipped)}, Platt-calibrated on held-out seasons")
    notes.extend(_ignored_inputs_notes(x))
    return FrostPrediction(
        probability=round(min(max(prob, 0.0), 1.0), 4), point_c=round(qs[0.5], 2),
        band_low_c=round(band_low, 2), band_high_c=round(band_high, 2), method="model",
        model_version=art.get("version", VERSION), calibrated=True, notes=notes,
    )


def predict(features: FrostFeatures) -> FrostPrediction:
    """Calibrated P(event) with an 80% temperature band. Falls back to the rule when the artifact is
    missing or the model fails; never raises for a missing artifact."""
    _check(features)
    art = load_artifact()
    if art is None:
        return rule_predict(features, notes=[f"model artifact not found or unreadable at {artifact_path()}"])
    try:
        return _model_predict(art, features)
    except Exception as e:  # never let a model bug take the decision down; degrade to the rule
        log.exception("frost model failed; using rule")
        return rule_predict(features, notes=[f"model error ({type(e).__name__}); rule used"])
