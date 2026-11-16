"""Heavy-rain rule (docs/MODEL_CARDS.md): the fraction of ECMWF IFS ensemble members whose 24 h rain total
reaches the IMD "heavy" category. Deterministic, uncalibrated, registered in model_registry like the other
components so every served output is traceable (PRD §8.3)."""
from __future__ import annotations

VERSION = "ensemble-rule-2026.11"
IMD_HEAVY_24H_MM = 64.5
MIN_REPORTED_P = 0.10   # below this the engine reports no heavy-rain risk
RULE = "fraction of ECMWF ensemble members with 24 h rain >= 64.5 mm (IMD heavy)"
HORIZON_DAYS = 3
