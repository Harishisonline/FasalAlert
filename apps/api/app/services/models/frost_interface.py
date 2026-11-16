"""Interface contract for the frost and heat classifier (PRD §9.1).

The decision engine depends only on this module. `frost.py` implements `predict`
and must keep these dataclasses stable. Training lives in scripts/train_frost.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Kind = Literal["frost", "heat"]
Method = Literal["model", "rule"]


@dataclass(frozen=True)
class FrostFeatures:
    kind: Kind                       # "frost": P(Tmin < threshold); "heat": P(Tmax > threshold)
    lat: float
    lon: float
    valid_date: date                 # local (IST) date the event would occur
    lead_hours: int                  # hours from forecast issue time to the event
    threshold_c: float               # crop-stage threshold (after farmer calibration)
    forecast_c: float                # forecast Tmin (frost) or Tmax (heat), deterministic or ensemble mean
    ensemble_spread_c: float | None = None   # ensemble standard deviation when available
    forecast_rain_mm: float | None = None
    observed_lags_c: tuple[float | None, float | None, float | None] = (None, None, None)  # t-1, t-2, t-3
    elevation_m: float | None = None
    station_distance_km: float | None = None
    antecedent_wetness: float | None = None  # e.g. 7-day rainfall sum, mm


@dataclass(frozen=True)
class FrostPrediction:
    probability: float               # calibrated P(event), 0..1
    point_c: float                   # best estimate of Tmin/Tmax
    band_low_c: float | None         # 80% band (10th percentile)
    band_high_c: float | None        # 80% band (90th percentile)
    method: Method                   # "model" = trained artifact, "rule" = PRD §9.1 fallback
    model_version: str
    calibrated: bool
    notes: list[str] = field(default_factory=list)
