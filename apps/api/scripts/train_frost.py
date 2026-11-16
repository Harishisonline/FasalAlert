"""Train, validate and ship the FasalAlert frost and heat classifier (PRD §9.1).

    uv run python scripts/train_frost.py            # downloads anything not cached, then trains
    uv run python scripts/train_frost.py --offline  # cache only (fails if a file is missing)

Approach (details and caveats in docs/model_cards/frost.md):
  * Target: IMD 1 degree gridded daily Tmin (frost) and Tmax (heat) at 33 Maharashtra cells.
  * Forecast: archived JMA GSM forecasts at 24/48/72 h leads (Open-Meteo Previous Runs API), the only
    free archive with 10 years at 48 h. Forecast-error model (stage 1) + calibrated classifiers
    (stage 2: logistic regression and a LightGBM challenger), threshold as an input.
  * Long IMD record: climatology features (1986-2015), Brier skill reference climatology (1996-2025,
    leaving the test season out), and long-run event counts and base rates (1951-2025).
  * Validation: leave-one-season-out (year-blocked) cross-validation; whole seasons are held out so no
    event straddles train and test; class-weighted fits recalibrated on held-out seasons. Frost is
    scored on Dec-Feb, heat on Mar-May.

Writes data/artifacts/frost/<version>/{model.joblib, metrics.json, reliability_frost.png,
reliability_heat.png}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.foundry import imd_grid, openmeteo_history  # noqa: E402
from app.services.models import frost as fm  # noqa: E402

log = logging.getLogger("train_frost")

VERSION = fm.VERSION
OUT_DIR = API_ROOT / "data" / "artifacts" / "frost" / VERSION
IMD_YEARS = range(1951, 2026)
RAIN_YEARS = range(2015, 2026)
FC_YEARS = range(2016, 2026)
FC_MODEL = "jma_seamless"
TRANSFER_MODEL = "best_match"         # what live serving (foundry/openmeteo.py) requests; evaluation only
TRANSFER_YEARS = range(2021, 2026)    # Dec 2021 to Dec 2025 scoring months
CLIM_FEATURE_YEARS = (1986, 2015)     # climatology the features are expressed against (disjoint from tests)
CLIM_REF_SEASONS = (1996, 2025)       # BSS reference: 30 recent seasons, test season left out
CLIM_ALT_SEASONS = (1986, 2015)       # alternative fixed reference, reported for sensitivity
HALF_WINDOW = 15                      # +-15 day window for climatology
ALERT_P = 0.5
ALERT_P_LOW = 0.25    # second, lower alert level reported for the decision engine's cost-loss choice
MIN_EVENTS = 30
SEED = 20261102
N_CELLS = 0  # set from the data in main()
DATES = pd.date_range("1951-01-01", "2025-12-31", freq="D")


@dataclass
class KindCfg:
    name: str
    var: str
    sign: float
    thr_train: np.ndarray
    thr_eval: list[float]
    eval_months: tuple[int, ...]
    season_doys: tuple[int, int]
    label: str = ""
    extra: dict = field(default_factory=dict)


# Evaluation thresholds include the crop table's own values (packages/shared/crops.json): mango flowering frost 4.4 °C,
# grape berry growth frost 7 °C, cotton mid-season heat 43 °C and its 45 °C override ceiling.
KINDS = {
    "frost": KindCfg("frost", "tmin", 1.0, np.arange(2.0, 14.01, 1.0), [4.0, 4.4, 6.0, 7.0, 8.0, 10.0], (12, 1, 2),
                     (fm.doy365(pd.Timestamp("2021-11-15")), fm.doy365(pd.Timestamp("2021-03-15"))),
                     "P(Tmin < threshold)"),
    "heat": KindCfg("heat", "tmax", -1.0, np.arange(34.0, 46.01, 1.0), [38.0, 40.0, 42.0, 43.0, 45.0], (3, 4, 5),
                    (fm.doy365(pd.Timestamp("2021-03-01")), fm.doy365(pd.Timestamp("2021-06-15"))),
                    "P(Tmax > threshold)"),
}


def season_of(dates: pd.DatetimeIndex | pd.Series, kind: str) -> np.ndarray:
    d = pd.DatetimeIndex(dates)
    if kind == "frost":
        return (d.year + (d.month >= 7)).to_numpy()
    return d.year.to_numpy()


def in_train_window(dates: pd.DatetimeIndex, kind: str) -> np.ndarray:
    m, dd = dates.month.to_numpy(), dates.day.to_numpy()
    if kind == "frost":
        return ((m == 11) & (dd >= 15)) | (m == 12) | (m == 1) | (m == 2) | ((m == 3) & (dd <= 15))
    return (m == 3) | (m == 4) | (m == 5) | ((m == 6) & (dd <= 15))


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
def to_matrix(df: pd.DataFrame, col: str, cells: list[tuple[float, float]]) -> np.ndarray:
    piv = df.pivot_table(index="date", columns=["lat", "lon"], values=col, aggfunc="first")
    piv = piv.reindex(index=DATES, columns=pd.MultiIndex.from_tuples(cells, names=["lat", "lon"]))
    return piv.to_numpy(dtype=float)


def load_inputs(offline: bool, max_cells: int | None = None) -> dict:
    cells = imd_grid.maharashtra_cells()[:max_cells]
    log.info("%d Maharashtra cells", len(cells))
    dl = not offline
    M: dict[str, np.ndarray] = {}
    for var in ("tmin", "tmax"):
        t0 = time.time()
        tidy = imd_grid.tidy_temperature(var, IMD_YEARS, cells, download=dl)
        M[var] = to_matrix(tidy, var, cells)
        log.info("IMD %s: %d rows, %.0fs", var, len(tidy), time.time() - t0)
    rain = imd_grid.tidy_rain_on_1deg(RAIN_YEARS, cells, download=dl)
    R = to_matrix(rain, "rain", cells)
    M["wet7"] = pd.DataFrame(R).rolling(7, min_periods=5).sum().to_numpy()
    elev = openmeteo_history.fetch_elevation(cells, offline=offline)
    fc = openmeteo_history.download_cells(cells, FC_YEARS, model=FC_MODEL, offline=offline)
    fc["date"] = pd.to_datetime(fc["date"])
    for L in fm.LEADS:
        for v in ("tmin", "tmax", "rain"):
            M[f"f_{v}_d{L}"] = to_matrix(fc, f"f_{v}_d{L}", cells)
    bm = openmeteo_history.download_cells(cells, TRANSFER_YEARS, model=TRANSFER_MODEL, offline=offline,
                                          windows=openmeteo_history.scoring_windows)
    bm["date"] = pd.to_datetime(bm["date"])
    M_bm = {f"f_{v}_d{L}": to_matrix(bm, f"f_{v}_d{L}", cells) for L in fm.LEADS for v in ("tmin", "tmax", "rain")}
    prov = {
        "imd_tmin": imd_grid.provenance("tmin", IMD_YEARS),
        "imd_tmax": imd_grid.provenance("tmax", IMD_YEARS),
        "imd_rain": imd_grid.provenance("rain", RAIN_YEARS),
        "openmeteo": openmeteo_history.cache_inventory(FC_MODEL),
    }
    shas = sorted(r["sha256"] for k in ("imd_tmin", "imd_tmax", "imd_rain") for r in prov[k])
    prov["imd_fingerprint_sha256"] = hashlib.sha256("".join(shas).encode()).hexdigest()
    om_files = sorted((openmeteo_history.DEFAULT_CACHE / "previous_runs" / FC_MODEL).glob("*.meta.json"))
    prov["openmeteo_fingerprint_sha256"] = hashlib.sha256(
        "".join(json.loads(f.read_text())["sha256"] for f in om_files).encode()).hexdigest()
    prov["openmeteo_transfer"] = openmeteo_history.cache_inventory(TRANSFER_MODEL)
    return {"cells": cells, "M": M, "M_bm": M_bm, "elev": [elev.get(c) for c in cells], "prov": prov,
            "fc_elev": fc.groupby(["lat", "lon"])["om_elevation_m"].first().to_dict()}


def climatology_arrays(T: np.ndarray, years: tuple[int, int]) -> np.ndarray:
    """(ncells, 366, 2): mean and std per cell and doy (1..365) over `years`, +-15 day circular window."""
    from scipy.ndimage import convolve1d

    mask = (DATES.year >= years[0]) & (DATES.year <= years[1])
    dd = fm.doy365_series(pd.Series(DATES[mask]))
    V = T[mask]
    ok = np.isfinite(V)
    S1 = np.zeros((366, V.shape[1]))
    S2 = np.zeros_like(S1)
    N = np.zeros_like(S1)
    np.add.at(S1, dd, np.where(ok, V, 0.0))
    np.add.at(S2, dd, np.where(ok, V, 0.0) ** 2)
    np.add.at(N, dd, ok)
    k = np.ones(2 * HALF_WINDOW + 1)
    S1w, S2w, Nw = (convolve1d(a[1:], k, axis=0, mode="wrap") for a in (S1, S2, N))
    mean = S1w / Nw
    std = np.sqrt(np.maximum(S2w / Nw - mean ** 2, 0.04))
    out = np.zeros((V.shape[1], 366, 2))
    out[:, 1:, 0], out[:, 1:, 1] = mean.T, std.T
    out[:, 0] = out[:, 365]
    return out


class ClimProb:
    """Climatological P(event) per cell, season and doy, from IMD seasons in a reference range, with an
    optional leave-test-season-out."""

    def __init__(self, T: np.ndarray, kind: str, thr: float, seasons: tuple[int, int]) -> None:
        from scipy.ndimage import convolve1d

        sgn = KINDS[kind].sign
        sea = season_of(DATES, kind)
        mask = (sea >= seasons[0]) & (sea <= seasons[1])
        dd = fm.doy365_series(pd.Series(DATES[mask]))
        V = T[mask]
        ok = np.isfinite(V)
        ev = ok & (sgn * np.where(ok, V, 0.0) < sgn * thr)
        si = sea[mask] - seasons[0]
        ns = seasons[1] - seasons[0] + 1
        E = np.zeros((ns, 366, V.shape[1]))
        N = np.zeros_like(E)
        np.add.at(E, (si, dd), ev)
        np.add.at(N, (si, dd), ok)
        k = np.ones(2 * HALF_WINDOW + 1)
        self.E = convolve1d(E[:, 1:], k, axis=1, mode="wrap")
        self.N = convolve1d(N[:, 1:], k, axis=1, mode="wrap")
        self.Et, self.Nt = self.E.sum(0), self.N.sum(0)
        self.s0, self.ns = seasons[0], ns

    def prob(self, season: np.ndarray, doy: np.ndarray, j: np.ndarray, loso: bool) -> np.ndarray:
        E, N = self.Et[doy - 1, j].copy(), self.Nt[doy - 1, j].copy()
        if loso:
            si = season - self.s0
            inside = (si >= 0) & (si < self.ns)
            E[inside] -= self.E[si[inside], doy[inside] - 1, j[inside]]
            N[inside] -= self.N[si[inside], doy[inside] - 1, j[inside]]
        return E / np.maximum(N, 1)


def build_samples(kind: str, D: dict, clim: np.ndarray, src: str = "M") -> pd.DataFrame:
    """Samples for one kind. `src` selects the forecast source: "M" = JMA (training), "M_bm" = best_match
    (evaluation only). Observations, rain and climatology always come from IMD."""
    cfg = KINDS[kind]
    M, cells = D["M"], D["cells"]
    FC = D[src]
    s = cfg.sign
    T = M[cfg.var]
    win = in_train_window(DATES, kind)
    months = DATES.month.to_numpy()
    doy_all = fm.doy365_series(pd.Series(DATES))
    sea_all = season_of(DATES, kind)
    frames = []
    for L in fm.LEADS:
        F = FC[f"f_{cfg.var}_d{L}"]
        di, j = np.nonzero(win[:, None] & np.isfinite(F) & np.isfinite(T))
        issue = di - L
        if kind == "frost":   # Tmin of the issue morning is known by the morning run
            lag_idx = [issue, issue - 1, issue - 2]
        else:                 # Tmax of the issue day is not known until evening
            lag_idx = [issue - 1, issue - 2, issue - 3]
        doy = doy_all[di]
        base = fm.frame_from_columns(s * F[di, j], np.full(len(di), L), doy, [cells[k][0] for k in j],
                                     [cells[k][1] for k in j], FC[f"f_rain_d{L}"][di, j], M["wet7"][issue, j],
                                     s * clim[j, doy, 0], clim[j, doy, 1], j)
        base["wet7_missing"] = ~np.isfinite(M["wet7"][issue, j])
        base["y"] = s * T[di, j]
        base["T_obs"] = T[di, j]
        base["f_raw"] = F[di, j]
        base["j"] = j
        base["di"] = di
        base["date"] = DATES[di]
        base["season"] = sea_all[di]
        base["eval"] = np.isin(months[di], cfg.eval_months)
        for k, li in enumerate(lag_idx, start=1):
            base[f"lag{k}"] = s * T[li, j]
        frames.append(base)
    out = pd.concat(frames, ignore_index=True)
    return out


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------
class ErrorModelLags(fm.ErrorModel):
    """Ablation only (never shipped): stage 1 plus observed-lag features."""

    def _xm(self, df: pd.DataFrame) -> np.ndarray:
        return np.column_stack([fm.x_mu(df, self.n_cells), df["lag1"] - df["cm"], df["f"] - df["lag1"], df["lag2"] - df["cm"],
                                df["lag3"] - df["cm"]])

    def _xs(self, df: pd.DataFrame) -> np.ndarray:
        return np.column_stack([fm.x_sigma(df, self.n_cells), np.abs(df["f"] - df["lag1"])])


def stack(df: pd.DataFrame, thr_s: np.ndarray, max_rows: int | None, rng: np.random.Generator):
    n, k = len(df), len(thr_s)
    rows = np.repeat(np.arange(n), k)
    thr = np.tile(thr_s, n)
    if max_rows is not None and len(rows) > max_rows:
        pick = np.sort(rng.choice(len(rows), max_rows, replace=False))
        rows, thr = rows[pick], thr[pick]
    sub = df.iloc[rows].reset_index(drop=True)
    o = (sub["y"].to_numpy() < thr).astype(int)
    return sub, thr, o, sub["season"].to_numpy()


def make_lr():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))


def make_gb(quick: bool):
    from lightgbm import LGBMClassifier

    return LGBMClassifier(
        n_estimators=120 if quick else 300, learning_rate=0.08 if quick else 0.05, num_leaves=31,
        min_child_samples=400, subsample=0.8, subsample_freq=1, colsample_bytree=0.9, reg_lambda=1.0,
        monotone_constraints=fm.GB_MONOTONE, class_weight="balanced", random_state=SEED, n_jobs=8,
        deterministic=True, force_row_wise=True, verbose=-1)


def calibrated(est, X, y, groups):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import GroupKFold

    splits = list(GroupKFold(n_splits=3).split(X, y, groups))
    cal = CalibratedClassifierCV(est, method="sigmoid", cv=splits, ensemble=False).fit(X, y)
    cal.cv = 3  # drop the stored split index arrays (tens of MB); prediction does not use them
    return cal


def fit_all(tr: pd.DataFrame, cfg: KindCfg, quick: bool, rng: np.random.Generator) -> dict:
    em = fm.ErrorModel(n_cells=N_CELLS).fit(tr, tr["y"].to_numpy(), groups=tr["season"].to_numpy())
    thr_s = cfg.sign * cfg.thr_train
    sub, thr, o, grp = stack(tr, thr_s, None, rng)
    lr = calibrated(make_lr(), fm.lr_design(sub, thr, em), o, grp)
    sub, thr, o, grp = stack(tr, thr_s, 250_000 if quick else 700_000, rng)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        gb = calibrated(make_gb(quick), fm.gb_design(sub, thr), o, grp)
    return {"error_model": em, "lr": lr, "gb": gb, "rule": rule_quantiles(tr, cfg)}


def rule_quantiles(tr: pd.DataFrame, cfg: KindCfg) -> dict[int, dict[str, np.ndarray]]:
    """Fallback rule table per lead, scoring months only: a per-cell straight line from forecast to
    observed (T_obs = a + b * forecast, b clipped to 0.3..1.2), and the empirical quantiles of the
    pooled residual. A plain per-cell median offset was tried first and scored worse than climatology
    because JMA's cold and hot extremes are overdone (conditional bias)."""
    ev = tr[tr["eval"]]
    out = {}
    for L, g in ev.groupby("L"):
        T, f, j = g["T_obs"].to_numpy(), g["f_raw"].to_numpy(), g["j"].to_numpy()
        a = np.zeros(N_CELLS)
        b = np.ones(N_CELLS)
        pooled_b = float(np.clip(np.polyfit(f, T, 1)[0], 0.3, 1.2))
        a[:] = float(np.mean(T - pooled_b * f))
        b[:] = pooled_b
        for jj in np.unique(j):
            m = j == jj
            if m.sum() >= 200:
                bj = float(np.clip(np.polyfit(f[m], T[m], 1)[0], 0.3, 1.2))
                b[jj], a[jj] = bj, float(np.mean(T[m] - bj * f[m]))
        r = T - (a[j] + b[j] * f)
        out[int(L)] = {"a": a, "b": b, "q": np.quantile(r, fm.PROBS)}
    return out


def rule_prob(kind: str, f_raw: np.ndarray, j: np.ndarray, thr: float, tab: dict[str, np.ndarray]) -> np.ndarray:
    p_below = fm._tail_cdf(thr - (tab["a"][j] + tab["b"][j] * f_raw), tab["q"], fm.PROBS)
    return p_below if kind == "frost" else 1.0 - p_below


def predict_block(models: dict, te: pd.DataFrame, cfg: KindCfg, thr: float) -> dict[str, np.ndarray]:
    thr_s = np.full(len(te), cfg.sign * thr)
    ka = {"error_model": models["error_model"], "lr": models["lr"], "gb": models["gb"]}
    out = {"p_lr": fm.classifier_proba(ka, "lr", te, thr_s), "p_gb": fm.classifier_proba(ka, "gb", te, thr_s),
           "p_em": models["error_model"].cdf(te, thr_s)}
    p_rule = np.empty(len(te))
    for L, idx in te.groupby("L").indices.items():
        p_rule[idx] = rule_prob(cfg.name, te["f_raw"].to_numpy()[idx], te["j"].to_numpy()[idx], thr,
                                models["rule"][L])
    out["p_rule"] = p_rule
    det = te["f_raw"].to_numpy() < thr if cfg.name == "frost" else te["f_raw"].to_numpy() > thr
    out["p_det"] = det.astype(float)
    return out


# ---------------------------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------------------------
def brier(p, o) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(o)) ** 2))


def reliability(p: np.ndarray, o: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        rows.append({"bin": [round(edges[b], 2), round(edges[b + 1], 2)], "n": int(m.sum()),
                     "mean_p": round(float(p[m].mean()), 4) if m.any() else None,
                     "obs_freq": round(float(o[m].mean()), 4) if m.any() else None})
    return rows


def spells(g: pd.DataFrame, flag: np.ndarray) -> list[np.ndarray]:
    """Runs of consecutive days (same cell) where flag is true. g sorted by j, date."""
    out = []
    j = g["j"].to_numpy()
    di = g["di"].to_numpy()
    idx = np.nonzero(flag)[0]
    if len(idx) == 0:
        return out
    brk = np.nonzero((np.diff(idx) != 1) | (np.diff(j[idx]) != 0) | (np.diff(di[idx]) != 1))[0]
    starts = np.concatenate([[0], brk + 1])
    ends = np.concatenate([brk + 1, [len(idx)]])
    return [idx[a:b] for a, b in zip(starts, ends, strict=True)]


def event_scores(g: pd.DataFrame, p: np.ndarray, o: np.ndarray, level: float = ALERT_P) -> dict:
    ev = spells(g, o.astype(bool))
    al = spells(g, p >= level)
    hit_ev = sum(bool((p[e] >= level).any()) for e in ev)
    true_al = sum(bool(o[a].any()) for a in al)
    tp = int(((p >= level) & (o == 1)).sum())
    return {
        "alert_at_p": level,
        "n_alert_spells": len(al),
        "event_recall": (hit_ev / len(ev)) if ev else None,
        "event_precision": (true_al / len(al)) if al else None,
        "day_recall": (tp / int(o.sum())) if o.sum() else None,
        "day_precision": (tp / int((p >= level).sum())) if (p >= level).sum() else None,
    }


def bss_ci(g: pd.DataFrame, pcol: str, ccol: str, rng: np.random.Generator, B: int = 1000) -> list[float] | None:
    agg = g.assign(em=(g[pcol] - g["o"]) ** 2, ec=(g[ccol] - g["o"]) ** 2).groupby("season")[["em", "ec"]].sum()
    if len(agg) < 3:
        return None
    em, ec = agg["em"].to_numpy(), agg["ec"].to_numpy()
    draws = rng.integers(0, len(agg), size=(B, len(agg)))
    den = ec[draws].sum(1)
    ok = den > 1e-9  # resamples that drew only event-free seasons have no defined skill score
    if ok.mean() < 0.9:
        return None
    vals = 1 - em[draws].sum(1)[ok] / den[ok]
    return [round(float(np.quantile(vals, 0.025)), 4), round(float(np.quantile(vals, 0.975)), 4)]


MODEL_COLS = {"lr": "p_lr", "lightgbm": "p_gb", "error_model": "p_em", "rule": "p_rule",
              "raw_deterministic": "p_det", "climatology_1996_2025_loso": "p_clim",
              "climatology_1986_2015": "p_clim86"}


def score(oof: pd.DataFrame, rng: np.random.Generator) -> dict:
    out = {}
    for (thr, L), g in oof.groupby(["thr", "L"]):
        g = g.sort_values(["j", "di"]).reset_index(drop=True)
        o = g["o"].to_numpy()
        ev = spells(g, o.astype(bool))
        n_events = len(ev)
        prelim = n_events < MIN_EVENTS
        res = {
            "lead_h": int(L * 24), "n_samples": int(len(g)), "n_positive_cell_days": int(o.sum()),
            "n_events": n_events, "n_event_dates": int(g.loc[o == 1, "date"].nunique()),
            "n_seasons": int(g["season"].nunique()),
            "n_seasons_with_events": int(g.loc[o == 1, "season"].nunique()),
            "calendar_years": sorted(int(y) for y in g["date"].dt.year.unique()),
            "base_rate": round(float(o.mean()), 5), "preliminary": bool(prelim),
            "brier": {}, "bss_vs_climatology": {}, "bss_vs_climatology_1986_2015": {},
        }
        bc = brier(g["p_clim"], o)
        bc86 = brier(g["p_clim86"], o)
        has_events = bool(o.sum() > 0)  # with no events a skill score only measures false-alarm cost
        for name, col in MODEL_COLS.items():
            b = brier(g[col], o)
            res["brier"][name] = round(b, 6)
            if not name.startswith("climatology"):
                res["bss_vs_climatology"][name] = round(1 - b / bc, 4) if has_events and bc > 0 else None
                res["bss_vs_climatology_1986_2015"][name] = (round(1 - b / bc86, 4) if has_events and bc86 > 0
                                                             else None)
        res["bss_95ci_season_bootstrap"] = {m: (bss_ci(g, MODEL_COLS[m], "p_clim", rng) if has_events else None)
                                            for m in ("lr", "lightgbm")}
        res["alert_at_p"] = ALERT_P
        for m in ("lr", "lightgbm", "rule"):
            for level, key in ((ALERT_P, f"events_{m}"), (ALERT_P_LOW, f"events_{m}_p{int(ALERT_P_LOW * 100)}")):
                es = event_scores(g, g[MODEL_COLS[m]].to_numpy(), o, level)
                if prelim:
                    es["event_recall"] = "n/a"
                    es["day_recall"] = "n/a"
                res[key] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in es.items()}
        late = g["season"].to_numpy() >= 2019  # all three leads exist from the 2019 season
        if late.any() and o[late].sum() > 0:
            bcl = brier(g.loc[late, "p_clim"], o[late])
            res["bss_vs_climatology_seasons_2019_on"] = {
                m: round(1 - brier(g.loc[late, MODEL_COLS[m]], o[late]) / bcl, 4) for m in ("lr", "lightgbm", "rule")}
        else:
            res["bss_vs_climatology_seasons_2019_on"] = None
        if L == 2:
            res["reliability"] = {m: reliability(g[MODEL_COLS[m]].to_numpy(), o) for m in ("lr", "lightgbm", "rule")}
            by_s = {}
            for sea, gs in g.groupby("season"):
                os_ = gs["o"].to_numpy()
                bcs = brier(gs["p_clim"], os_)
                row = {"n": int(len(gs)), "n_positive": int(os_.sum()), "brier_climatology": round(bcs, 6)}
                for m in ("lr", "lightgbm"):
                    bm_ = brier(gs[MODEL_COLS[m]], os_)
                    row[f"brier_{m}"] = round(bm_, 6)
                    row[f"bss_{m}"] = round(1 - bm_ / bcs, 4) if os_.sum() > 0 and bcs > 0 else None
                by_s[str(int(sea))] = row
            res["by_season"] = by_s
        out.setdefault(f"{thr:g}C", {})[f"{int(L * 24)}h"] = res
    return out


def transfer_scores(oof: pd.DataFrame, bm: pd.DataFrame | None) -> dict:
    """The classifier is trained on JMA forecasts; live serving passes best_match. Score both inputs on
    the same held-out rows (cell, day, lead) so only the forecast source differs."""
    if bm is None or bm.empty:
        return {"status": "no data"}
    out = {"forecast_model": TRANSFER_MODEL, "note": "same out-of-fold models; matched rows only"}
    tm = bm[bm["thr"].isna()]
    pr = bm[bm["thr"].notna()]
    keys = ["j", "di", "L", "thr"]
    m = oof.merge(pr, on=keys, suffixes=("_jma", "_bm"))
    for (thr, L), g in m.groupby(["thr", "L"]):
        o = g["o_jma"].to_numpy()
        bc = brier(g["p_clim_jma"], o)
        has = bool(o.sum() > 0)
        row = {"n_samples": int(len(g)), "n_positive_cell_days": int(o.sum()),
               "n_seasons": int(g["season_jma"].nunique()), "brier_climatology": round(bc, 6)}
        for mname, col in (("lr", "p_lr"), ("lightgbm", "p_gb"), ("rule", "p_rule")):
            for src in ("jma", "bm"):
                b = brier(g[f"{col}_{src}"], o)
                row[f"brier_{mname}_{src}_input"] = round(b, 6)
                row[f"bss_{mname}_{src}_input"] = round(1 - b / bc, 4) if has and bc > 0 else None
        out.setdefault(f"{thr:g}C", {})[f"{int(L * 24)}h"] = row
    tt = {}
    for L, g in tm.groupby("L"):
        tt[f"{int(L * 24)}h"] = {"n": int(len(g)),
                                 "mae_raw_forecast_c": round(float((g["T_obs"] - g["f_raw"]).abs().mean()), 3),
                                 "bias_raw_forecast_c": round(float((g["T_obs"] - g["f_raw"]).mean()), 3),
                                 "mae_corrected_median_c": round(float((g["T_obs"] - g["q50"]).abs().mean()), 3)}
    out["temperature_forecast"] = tt
    return out


def temperature_scores(tmp: pd.DataFrame) -> dict:
    out = {}
    for L, g in tmp.groupby("L"):
        e_raw = g["T_obs"] - g["f_raw"]
        out[f"{int(L * 24)}h"] = {
            "n": int(len(g)),
            "mae_raw_forecast_c": round(float(e_raw.abs().mean()), 3),
            "bias_raw_forecast_c": round(float(e_raw.mean()), 3),
            "mae_corrected_median_c": round(float((g["T_obs"] - g["q50"]).abs().mean()), 3),
            "band80_coverage": round(float(((g["T_obs"] >= g["lo"]) & (g["T_obs"] <= g["hi"])).mean()), 4),
            "band80_mean_width_c": round(float((g["hi"] - g["lo"]).mean()), 3),
            "by_season": {str(int(sea)): {"bias_raw_c": round(float((gs["T_obs"] - gs["f_raw"]).mean()), 3),
                                          "mae_raw_c": round(float((gs["T_obs"] - gs["f_raw"]).abs().mean()), 3),
                                          "mae_corrected_c": round(float((gs["T_obs"] - gs["q50"]).abs().mean()), 3)}
                          for sea, gs in g.groupby("season")},
        }
    return out


def long_record(T: np.ndarray, kind: str) -> dict:
    cfg = KINDS[kind]
    sea = season_of(DATES, kind)
    m = np.isin(DATES.month.to_numpy(), cfg.eval_months)
    first_full = 1952 if kind == "frost" else 1951
    keep = m & (sea >= first_full) & (sea <= 2025)
    out = {"seasons": [first_full, 2025], "note": "IMD 1 degree, all 33 cells, scoring months only"}
    di = np.nonzero(keep)[0]
    gap = np.concatenate([[True], np.diff(di) != 1])  # rows that do not follow the previous calendar day
    for thr in cfg.thr_eval:
        V = T[keep]
        ev = (cfg.sign * V < cfg.sign * thr) & np.isfinite(V)
        s_k = sea[keep]
        n_sp = 0
        per_period = {"1952-1985" if kind == "frost" else "1951-1985": 0, "1986-2015": 0, "2016-2025": 0}
        for jj in range(V.shape[1]):
            e = ev[:, jj]
            prev = np.concatenate([[False], e[:-1]])
            starts = np.nonzero(e & (~prev | gap))[0]  # a spell is a run of consecutive calendar days
            n_sp += len(starts)
            for st in starts:
                y = s_k[st]
                key = list(per_period)[0] if y <= 1985 else ("1986-2015" if y <= 2015 else "2016-2025")
                per_period[key] += 1
        out[f"{thr:g}C"] = {
            "positive_cell_days": int(ev.sum()), "cell_spells": int(n_sp),
            "seasons_with_event": int(len(np.unique(s_k[ev.any(1)]))), "n_seasons": int(len(np.unique(s_k))),
            "cell_spells_by_period": per_period,
            "base_rate": round(float(ev.mean()), 5),
        }
    return out


# ---------------------------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------------------------
COLORS = {"lr": "#2a78d6", "lightgbm": "#eb6834", "rule": "#1baf7a"}
LABELS = {"lr": "Logistic regression", "lightgbm": "LightGBM", "rule": "Rule (fallback)"}


def plot_reliability(kind: str, scores: dict, path: Path, shipped: str) -> None:
    import matplotlib
    import matplotlib.ticker

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cfg = KINDS[kind]
    thrs = [f"{t:g}C" for t in cfg.thr_eval]
    fig, axes = plt.subplots(2, len(thrs), figsize=(3.6 * len(thrs), 5.6), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor("#fcfcfb")
    for c, t in enumerate(thrs):
        r = scores[t]["48h"]
        ax, axh = axes[0, c], axes[1, c]
        for a in (ax, axh):
            a.set_facecolor("#fcfcfb")
            for sp in ("top", "right"):
                a.spines[sp].set_visible(False)
            a.spines["left"].set_color("#9a9994")
            a.spines["bottom"].set_color("#9a9994")
            a.tick_params(colors="#52514e", labelsize=8)
        ax.plot([0, 1], [0, 1], color="#b5b4ae", lw=1, ls="--", zorder=1)
        width = 0.028
        for k, m in enumerate(("lr", "lightgbm", "rule")):
            rel = [b for b in r["reliability"][m] if b["n"] >= 20]
            if rel:
                ax.plot([b["mean_p"] for b in rel], [b["obs_freq"] for b in rel], marker="o", ms=4.5, lw=2,
                        color=COLORS[m], label=LABELS[m] + (" (shipped)" if m == shipped else ""), zorder=3)
            allb = r["reliability"][m]
            centers = np.array([np.mean(b["bin"]) for b in allb]) + (k - 1) * width
            nz = [i for i, b in enumerate(allb) if b["n"] > 0]
            axh.bar(centers[nz], [allb[i]["n"] for i in nz], width=width * 0.9, color=COLORS[m], zorder=2)
        axh.set_yscale("log")
        axh.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        thr_txt = f"Tmin < {t[:-1]} °C" if kind == "frost" else f"Tmax > {t[:-1]} °C"
        tag = "  PRELIMINARY" if r["preliminary"] else ""
        bss = {k: ("n/a" if v is None else f"{v:.3f}") for k, v in r["bss_vs_climatology"].items()}
        n_ev = r["n_events"]
        ax.set_title(f"{thr_txt}, 48 h{tag}\n{n_ev} event{'' if n_ev == 1 else 's'}, BSS LR {bss['lr']}, "
                     f"LightGBM {bss['lightgbm']}",
                     fontsize=8.5, color="#0b0b0b")
        axh.set_xlabel("Forecast probability", fontsize=8, color="#52514e")
        if c == 0:
            ax.set_ylabel("Observed frequency", fontsize=8, color="#52514e")
            axh.set_ylabel("Count", fontsize=8, color="#52514e")
            ax.legend(fontsize=7.5, frameon=False, loc="upper left")
        ax.grid(color="#e8e7e3", lw=0.6, zorder=0)
    months = "Dec-Feb" if kind == "frost" else "Mar-May"
    fig.suptitle(f"{VERSION} {kind}: reliability at 48 h, leave-one-season-out, IMD 1° Maharashtra, {months} "
                 f"2016-2025 (bins with n < 20 not drawn)", fontsize=9.5, color="#0b0b0b")
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
def run_kind(kind: str, D: dict, clim: np.ndarray, quick: bool, rng: np.random.Generator) -> dict:
    cfg = KINDS[kind]
    T = D["M"][cfg.var]
    data = build_samples(kind, D, clim)
    seasons = sorted(data["season"].unique())
    log.info("%s: %d samples (%d in scoring months), seasons %s", kind, len(data), int(data["eval"].sum()), seasons)
    cps = {thr: (ClimProb(T, kind, thr, CLIM_REF_SEASONS), ClimProb(T, kind, thr, CLIM_ALT_SEASONS))
           for thr in cfg.thr_eval}
    data_bm = build_samples(kind, D, clim, src="M_bm")
    data_bm = data_bm[data_bm["eval"]].reset_index(drop=True)
    log.info("%s: %d %s scoring samples for the transfer test", kind, len(data_bm), TRANSFER_MODEL)
    oof_parts, tmp_parts, abl_parts, bm_parts = [], [], [], []
    folds = seasons if not quick else seasons[::3]
    for s_test in folds:
        t0 = time.time()
        tr = data[data["season"] != s_test].reset_index(drop=True)
        te = data[(data["season"] == s_test) & data["eval"]].reset_index(drop=True)
        if len(te) == 0:
            continue
        models = fit_all(tr, cfg, quick, rng)
        em = models["error_model"]
        tmp = te[["L", "T_obs", "f_raw", "season", "j", "di"]].copy()
        q = {p: em.quantile(te, p) * cfg.sign for p in (0.1, 0.5, 0.9)}
        tmp["q50"] = q[0.5]
        tmp["lo"] = np.minimum(q[0.1], q[0.9])
        tmp["hi"] = np.maximum(q[0.1], q[0.9])
        tmp_parts.append(tmp)
        # Ablation: observed lags in stage 1 (same rows, lags must exist)
        trl = tr.dropna(subset=["lag1", "lag2", "lag3"]).reset_index(drop=True)
        tel = te.dropna(subset=["lag1", "lag2", "lag3"]).reset_index(drop=True)
        eml = ErrorModelLags(n_cells=N_CELLS).fit(trl, trl["y"].to_numpy(), groups=trl["season"].to_numpy())
        em0 = fm.ErrorModel(n_cells=N_CELLS).fit(trl, trl["y"].to_numpy(), groups=trl["season"].to_numpy())
        doy_te = te["doy"].to_numpy().astype(int)
        for thr in cfg.thr_eval:
            p = predict_block(models, te, cfg, thr)
            blk = te[["season", "date", "j", "di", "L"]].copy()
            blk["thr"] = thr
            blk["o"] = (te["y"].to_numpy() < cfg.sign * thr).astype(int)
            for k, v in p.items():
                blk[k] = v
            sea = te["season"].to_numpy()
            jj = te["j"].to_numpy()
            blk["p_clim"] = cps[thr][0].prob(sea, doy_te, jj, loso=True)
            blk["p_clim86"] = cps[thr][1].prob(sea, doy_te, jj, loso=False)
            oof_parts.append(blk)
            thr_s = np.full(len(tel), cfg.sign * thr)
            ab = tel[["season", "L"]].copy()
            ab["thr"] = thr
            ab["o"] = (tel["y"].to_numpy() < cfg.sign * thr).astype(int)
            ab["p_nolag"] = em0.cdf(tel, thr_s)
            ab["p_lag"] = eml.cdf(tel, thr_s)
            abl_parts.append(ab)
        te_bm = data_bm[data_bm["season"] == s_test].reset_index(drop=True)
        if len(te_bm):
            for thr in cfg.thr_eval:
                p = predict_block(models, te_bm, cfg, thr)
                blk = te_bm[["season", "date", "j", "di", "L"]].copy()
                blk["thr"] = thr
                blk["o"] = (te_bm["y"].to_numpy() < cfg.sign * thr).astype(int)
                for k, v in p.items():
                    blk[k] = v
                blk["p_clim"] = cps[thr][0].prob(te_bm["season"].to_numpy(), te_bm["doy"].to_numpy().astype(int),
                                                 te_bm["j"].to_numpy(), loso=True)
                bm_parts.append(blk)
            q50 = models["error_model"].quantile(te_bm, 0.5) * cfg.sign
            bm_parts.append(te_bm[["L", "T_obs", "f_raw", "j", "di", "season"]].assign(q50=q50, thr=np.nan))
        log.info("%s fold %s: %d test rows, %.0fs", kind, s_test, len(te), time.time() - t0)
    oof = pd.concat(oof_parts, ignore_index=True)
    tmp = pd.concat(tmp_parts, ignore_index=True)
    abl = pd.concat(abl_parts, ignore_index=True)

    # Event integrity: every event lies inside one held-out season
    straddle = 0
    for _, g in oof.groupby(["thr", "L"]):
        g = g.sort_values(["j", "di"]).reset_index(drop=True)
        for e in spells(g, g["o"].to_numpy().astype(bool)):
            straddle += int(g["season"].iloc[e].nunique() > 1)

    scores = score(oof, rng)
    transfer = transfer_scores(oof, pd.concat(bm_parts, ignore_index=True) if bm_parts else None)
    pooled = {m: round(brier(oof[c], oof["o"]), 6) for m, c in MODEL_COLS.items()}
    pooled48 = {m: round(brier(oof.loc[oof.L == 2, c], oof.loc[oof.L == 2, "o"]), 6) for m, c in MODEL_COLS.items()}
    shipped = "lr" if pooled["lr"] <= pooled["lightgbm"] else "gb"
    ablation = {}
    for (thr, L), g in abl.groupby(["thr", "L"]):
        b0, b1 = brier(g["p_nolag"], g["o"]), brier(g["p_lag"], g["o"])
        ablation.setdefault(f"{thr:g}C", {})[f"{int(L * 24)}h"] = {
            "brier_error_model_without_lags": round(b0, 6), "brier_error_model_with_lags": round(b1, 6),
            "relative_change": round((b1 - b0) / b0, 4) if b0 > 0 else None, "n": int(len(g))}

    # Final fit on all seasons
    t0 = time.time()
    final = fit_all(data.reset_index(drop=True), cfg, quick, rng)
    log.info("%s final fit %.0fs, shipped=%s", kind, time.time() - t0, shipped)
    final_rule = {int(L): {k: [round(float(v), 3) for v in t[k]] for k in ("a", "b", "q")}
                  for L, t in final["rule"].items()}
    return {
        "artifact": {"error_model": final["error_model"], "lr": final["lr"], "gb": final["gb"],
                     "shipped": shipped, "season_doys": cfg.season_doys,
                     "threshold_range": (float(cfg.thr_train.min()), float(cfg.thr_train.max())),
                     "sign": cfg.sign},
        "rule_table": final_rule,
        "metrics": {
            "event": cfg.label, "scoring_months": list(cfg.eval_months),
            "training_window": "15 Nov to 15 Mar" if kind == "frost" else "1 Mar to 15 Jun",
            "seasons_held_out": [int(s) for s in folds],
            "n_training_samples": int(len(data)),
            "wet7_missing_fraction": round(float(data["wet7_missing"].mean()), 4),
            "shipped": "logistic_regression" if shipped == "lr" else "lightgbm",
            "selection": "lower pooled Brier over scoring thresholds and leads, out of fold",
            "pooled_brier_all_leads": pooled, "pooled_brier_48h": pooled48,
            "events_straddling_folds": straddle,
            "by_threshold": scores,
            "temperature_forecast": temperature_scores(tmp),
            "ablation_observed_lags": ablation,
            "transfer_to_serving_model": transfer,
            "long_record_imd": long_record(T, kind),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    ap.add_argument("--quick", action="store_true", help="development run: every third fold, smaller GBM")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--max-cells", type=int, default=None, help="development only: first N cells")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    rng = np.random.default_rng(SEED)
    t_start = time.time()
    D = load_inputs(args.offline, args.max_cells)
    global N_CELLS
    N_CELLS = len(D["cells"])
    climatology = {k: climatology_arrays(D["M"][KINDS[k].var], CLIM_FEATURE_YEARS) for k in KINDS}
    results = {k: run_kind(k, D, climatology[k], args.quick, rng) for k in KINDS}

    import joblib
    import lightgbm
    import sklearn

    args.out.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    rule_table = {"cells": [[float(a), float(b)] for a, b in D["cells"]], **{k: results[k]["rule_table"] for k in KINDS}}
    artifact = {
        "version": VERSION, "trained_at": trained_at,
        "cells": [[float(a), float(b)] for a, b in D["cells"]],
        "cell_elevation_m": D["elev"],
        "clim": {k: climatology[k].astype(np.float32) for k in KINDS},
        "kinds": {k: results[k]["artifact"] for k in KINDS},
        "rule_table": rule_table, "probs": fm.PROBS.tolist(),
        "forecast_model": FC_MODEL,
        "libs": {"scikit-learn": sklearn.__version__, "lightgbm": lightgbm.__version__,
                 "numpy": np.__version__},
    }
    art_path = args.out / "model.joblib"
    joblib.dump(artifact, art_path, compress=3)
    for k in KINDS:
        plot_reliability(k, results[k]["metrics"]["by_threshold"], args.out / f"reliability_{k}.png",
                         results[k]["artifact"]["shipped"].replace("gb", "lightgbm"))

    prov = D["prov"]
    dataset_ref = (
        f"IMD Pune 1.0 deg gridded daily Tmin 1951-2025 ({imd_grid.SPECS['tmin'].page}, POST "
        f"{imd_grid.SPECS['tmin'].endpoint}) and Tmax 1951-2025 ({imd_grid.SPECS['tmax'].page}, POST "
        f"{imd_grid.SPECS['tmax'].endpoint}); IMD 0.25 deg gridded daily rainfall 2015-2025 "
        f"({imd_grid.SPECS['rain'].page}) averaged to 1 deg; Open-Meteo Previous Runs API "
        f"({openmeteo_history.PREVIOUS_RUNS_URL}) model {FC_MODEL}, hourly temperature_2m and precipitation "
        f"previous_day1..3, 2016-01-01 to 2025-12-31 (windows 1 Jan-15 Jun and 15 Nov-31 Dec), at 33 "
        f"Maharashtra 1 deg IMD cell centres; evaluation only: the same API with model {TRANSFER_MODEL}, "
        f"Dec 2021 to Dec 2025 scoring months; Open-Meteo elevation API ({openmeteo_history.ELEVATION_URL}). "
        f"IMD file fingerprint sha256 {prov['imd_fingerprint_sha256'][:16]}, Open-Meteo fingerprint "
        f"{prov['openmeteo_fingerprint_sha256'][:16]}."
    )
    head = {}
    for k in KINDS:
        bt = results[k]["metrics"]["by_threshold"]
        shipped_col = "lr" if results[k]["artifact"]["shipped"] == "lr" else "lightgbm"
        head[k] = {t: {"n_events": v["48h"]["n_events"], "preliminary": v["48h"]["preliminary"],
                       "brier": v["48h"]["brier"][shipped_col],
                       "bss_vs_climatology": v["48h"]["bss_vs_climatology"][shipped_col],
                       "bss_95ci": v["48h"]["bss_95ci_season_bootstrap"][shipped_col],
                       "event_recall": v["48h"][f"events_{shipped_col}"]["event_recall"],
                       "event_precision": v["48h"][f"events_{shipped_col}"]["event_precision"]}
                   for t, v in bt.items() if "48h" in v}
    metrics = {
        "name": "frost", "version": VERSION, "kind": "classifier", "dataset_ref": dataset_ref,
        "trained_at": trained_at,
        "metrics": {
            "headline_48h_shipped": head,
            "frost": results["frost"]["metrics"], "heat": results["heat"]["metrics"],
            "validation": {
                "scheme": "leave-one-season-out (year-blocked); every season held out whole, so no event "
                          "(consecutive-day run at a cell) straddles train and test",
                "event_definition": "a run of consecutive days at one 1 deg cell with the event true",
                "preliminary_rule": f"fewer than {MIN_EVENTS} events at 48 h: preliminary, recall n/a",
                "climatology_reference": f"IMD seasons {CLIM_REF_SEASONS[0]}-{CLIM_REF_SEASONS[1]} excluding "
                                         f"the test season, same cell, +-{HALF_WINDOW} days",
                "climatology_features": f"IMD {CLIM_FEATURE_YEARS[0]}-{CLIM_FEATURE_YEARS[1]}",
                "class_weighting": "balanced class weights, then Platt (sigmoid) recalibration on held-out "
                                   "seasons (inner 3-fold GroupKFold by season)",
                "lead_mapping": "24/48/72 h = Open-Meteo previous_day1/2/3 (about N*24 to N*24+6 h)",
                "quick_run": bool(args.quick),
            },
            "data": {"cells": len(D["cells"]), "imd_files": {k: len(prov[k]) for k in ("imd_tmin", "imd_tmax", "imd_rain")},
                     "imd_bytes": int(sum(r["bytes"] for k in ("imd_tmin", "imd_tmax", "imd_rain") for r in prov[k])),
                     "openmeteo_cache": prov["openmeteo"], "openmeteo_transfer_cache": prov["openmeteo_transfer"]},
            "rule_table": {"probs": fm.PROBS.tolist(), **rule_table},
            "runtime_s": round(time.time() - t_start, 1),
        },
        "thresholds": {
            "frost_eval_c": KINDS["frost"].thr_eval, "heat_eval_c": KINDS["heat"].thr_eval,
            "frost_trained_range_c": [2.0, 14.0], "heat_trained_range_c": [34.0, 46.0],
            "alert_probability": ALERT_P, "preliminary_min_events": MIN_EVENTS,
        },
        "artifact_path": f"data/artifacts/frost/{VERSION}/model.joblib",
        "notes": "",
    }
    metrics["notes"] = build_notes(results)
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=_json_default))
    size = art_path.stat().st_size
    log.info("artifact %s (%.2f MB), total %.0fs", art_path, size / 1e6, time.time() - t_start)
    check_rule_table(rule_table)


def build_notes(results: dict) -> str:
    parts = [
        "Forecast-error model (stage 1: bias and heteroscedastic spread of IMD minus JMA GSM, with an empirical "
        "residual distribution that gives the 80% band) plus calibrated classifiers with the threshold as an "
        "input (stage 2: logistic regression on the stage 1 margin and a climatological margin; LightGBM "
        "challenger with monotone constraints). Both class weighted and Platt-recalibrated on held-out seasons.",
        "Trained on archived JMA GSM forecasts, the only free archive with 10 years at 48 h. Live serving "
        "(foundry/openmeteo.py) passes Open-Meteo best_match; that transfer is scored separately below.",
        "1 degree IMD cell skill only: it cannot resolve a frost pocket, valley or slope inside a cell.",
        "Ensemble spread, station distance and observed lags are not model inputs (no training data or not "
        "available in real time); see the model card.",
    ]
    for k in KINDS:
        tr = results[k]["metrics"]["transfer_to_serving_model"]
        ship_t = "lr" if results[k]["artifact"]["shipped"] == "lr" else "lightgbm"
        bits = []
        for t, d in tr.items():
            r = d.get("48h") if isinstance(d, dict) else None
            if r and r.get(f"bss_{ship_t}_jma_input") is not None and r["n_positive_cell_days"] >= 30:
                bits.append(f"{t} {r[f'bss_{ship_t}_jma_input']} -> {r[f'bss_{ship_t}_bm_input']}")
        if bits:
            parts.append(f"{k} transfer test (same held-out rows, Dec 2021 to Dec 2025), 48 h BSS with JMA input -> "
                         f"best_match input: {'; '.join(bits)}. Skill drops; feed the classifier JMA forecasts.")
    for k in KINDS:
        bt = results[k]["metrics"]["by_threshold"]
        prelim = [t for t, v in bt.items() if v.get("48h", {}).get("preliminary")]
        if prelim:
            parts.append(f"{k}: preliminary (fewer than {MIN_EVENTS} events at 48 h) at {', '.join(prelim)}.")
        ship = "lr" if results[k]["artifact"]["shipped"] == "lr" else "lightgbm"
        nonpos = [t for t, v in bt.items() if (v.get("48h", {}).get("bss_vs_climatology", {}).get(ship) or 0) <= 0]
        if nonpos:
            parts.append(f"{k}: Brier skill score vs climatology not positive at 48 h for {', '.join(nonpos)}.")
    return " ".join(parts)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def _rule_literal(t: dict) -> str:
    lines = ["RULE_TABLE: dict[str, Any] = {",
             "    'cells': (" + ", ".join(f"({a}, {b})" for a, b in t["cells"]) + "),"]
    for k in KINDS:
        lines.append(f"    {k!r}: {{")
        for L, d in t[k].items():
            lines.append(f"        {int(L)}: {{")
            for key in ("a", "b", "q"):
                lines.append(f"            {key!r}: {tuple(d[key])!r},")
            lines.append("        },")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines)


def _rule_norm(t: dict) -> dict:
    if not t:
        return {}
    out = {"cells": [[float(a), float(b)] for a, b in t["cells"]]}
    for k in KINDS:
        out[k] = {int(L): {key: [float(v) for v in d[key]] for key in ("a", "b", "q")} for L, d in t[k].items()}
    return out


def check_rule_table(rule_table: dict) -> None:
    """frost.py embeds the rule table so the fallback works without the artifact. Warn if it is stale."""
    if _rule_norm(fm.RULE_TABLE) != _rule_norm(rule_table):
        log.warning("frost.RULE_TABLE differs from this run; paste this into app/services/models/frost.py:\n%s",
                    _rule_literal(rule_table))
    else:
        log.info("frost.RULE_TABLE matches this run")


if __name__ == "__main__":
    main()
