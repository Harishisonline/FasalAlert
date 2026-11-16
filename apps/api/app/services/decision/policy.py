"""Centralised decision policy (PRD §8.1 L3). Every rule the engine applies lives here, versioned.

Probability bins follow IMD's probability vocabulary (Unlikely < 25 %, Likely 25 to 50 %, Very likely
50 to 75 %, Most likely > 75 %), so a level always agrees with the words shown to the farmer.
"""
from __future__ import annotations

from datetime import datetime, timedelta

POLICY_VERSION = "policy-2026.11"

LEVELS = ("none", "low", "medium", "high", "critical")
ACTIONABLE = ("medium", "high", "critical")

# Sensitivity (R9b) = how far ahead a risk becomes actionable (PRD §7.10).
HORIZON_HOURS = {"low": 24, "normal": 48, "high": 72}

FORECAST_STALE_AFTER = timedelta(hours=3, minutes=15)   # one missed 3-hourly refresh + the 900 s TTL
MAX_BAND_WIDTH_C = 8.0      # an 80 % band wider than this is too uncertain to advise on
FROST_ACT_LEAD = timedelta(hours=8)                      # act the evening before a pre-dawn minimum
HEAT_ACT_LEAD = timedelta(hours=6)


def level_for(p: float, lead_hours: int, sensitivity: str = "normal") -> str:
    if p < 0.10:
        lvl = "none"
    elif p < 0.25:
        lvl = "low"
    elif p < 0.50:
        lvl = "medium"
    elif p < 0.75:
        lvl = "high"
    else:
        lvl = "critical" if lead_hours <= 48 else "high"
    if lead_hours > HORIZON_HOURS.get(sensitivity, 48) and LEVELS.index(lvl) > LEVELS.index("medium"):
        lvl = "medium"  # visible, but beyond the farmer's chosen lead time it is not yet urgent
    return lvl


def rank(level: str) -> int:
    return LEVELS.index(level)


def act_by(kind: str, event_at: datetime) -> datetime:
    lead = FROST_ACT_LEAD if kind == "frost" else HEAT_ACT_LEAD
    t = event_at - lead
    return t.replace(minute=0 if t.minute < 30 else 30, second=0, microsecond=0)


def too_uncertain(band_low: float | None, band_high: float | None, p: float) -> bool:
    if band_low is None or band_high is None:
        return False
    return (band_high - band_low) > MAX_BAND_WIDTH_C and 0.25 <= p <= 0.75


ADVISORY_QUERY = {
    "frost": ("frost protection cold injury low temperature irrigation smoke", "frost_protection"),
    "heatwave": ("heat stress high temperature protection irrigation", "heat_stress"),
    "heavy_rain": ("heavy rain waterlogging drainage protection", "rainfall_management"),
    "transport": ("harvest transport packing post-harvest handling", "transport"),
}
