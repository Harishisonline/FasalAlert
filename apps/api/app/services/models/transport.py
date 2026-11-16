"""Transport disruption susceptibility (PRD §9.3).

A transparent physical rule set, not a trained classifier: there is no public, machine-readable dataset
of Indian highway closures to train or calibrate against. The output is a 0..1 susceptibility score
reported in the `p_disruption` field with `calibrated: false`. It must always be described as
"risk from rainfall and terrain", never as a closure prediction (PRD §9.3, §12, §19.2 rule 5).

Rainfall is scaled against IMD's official rainfall intensity categories for 24 h totals:
heavy 64.5 to 115.5 mm, very heavy 115.6 to 204.4 mm, extremely heavy 204.5 mm or more.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

VERSION = "transport-2026.11"
NOTE = "Risk estimated from rainfall and terrain, not from observed closures."
IMD_HEAVY_24H = 64.5
IMD_VERY_HEAVY_24H = 115.6

# Relative exposure by road class (design assumption, documented in docs/model_cards/transport.md):
# lower classes have fewer engineered drains and more low causeways.
CLASS_FACTOR = {"national": 0.7, "state": 0.85, "district": 1.0, "village": 1.2, "other": 1.1}
LOGISTIC_K = 4.0


@dataclass(frozen=True)
class SegmentInput:
    segment_id: int
    road_class: str
    slope_pct: float | None
    low_lying: bool | None
    rain_mm_by_day: dict[date, float]   # daily totals: past (analysis) and forecast


@dataclass(frozen=True)
class SegmentDayRisk:
    segment_id: int
    day: date
    score: float          # 0..1 susceptibility
    rain_24h: float
    rain_72h: float
    antecedent_7d: float
    index: float


def _rain(d: dict[date, float], day: date) -> float:
    return float(d.get(day) or 0.0)


def susceptibility(seg: SegmentInput, day: date) -> SegmentDayRisk:
    r24 = _rain(seg.rain_mm_by_day, day)
    r72 = sum(_rain(seg.rain_mm_by_day, day - timedelta(days=i)) for i in range(3))
    ante = sum(_rain(seg.rain_mm_by_day, day - timedelta(days=i)) for i in range(3, 10))
    intensity = max(r24 / IMD_HEAVY_24H, r72 / IMD_VERY_HEAVY_24H)
    wetness = 1.0 + 0.5 * min(ante / 100.0, 1.0)          # wet ground sheds more runoff
    terrain = 1.0 + (0.5 if seg.low_lying else 0.0) + (0.3 if (seg.slope_pct or 0) > 6 else 0.0)
    index = intensity * wetness * terrain * CLASS_FACTOR.get(seg.road_class, 1.0)
    score = 1.0 / (1.0 + math.exp(-LOGISTIC_K * (index - 1.0)))
    return SegmentDayRisk(seg.segment_id, day, round(score, 3), r24, r72, ante, round(index, 3))


@dataclass(frozen=True)
class RouteDay:
    day: date
    p_disruption: float
    rain_mm: float
    worst_segment_id: int | None


def route_risk(segments: list[SegmentInput], days: list[date]) -> tuple[list[RouteDay], list[SegmentDayRisk]]:
    """Route score per day is the worst segment (weakest link), which avoids assuming independence."""
    per_seg: list[SegmentDayRisk] = []
    out: list[RouteDay] = []
    for d in days:
        risks = [susceptibility(s, d) for s in segments]
        per_seg += risks
        worst = max(risks, key=lambda r: r.score) if risks else None
        out.append(RouteDay(d, worst.score if worst else 0.0, worst.rain_24h if worst else 0.0,
                            worst.segment_id if worst else None))
    return out, per_seg


def level(p: float) -> str:
    """Design-default bins (design.md 14.12, Appendix B Q10) until calibration data exists."""
    if p >= 0.8:
        return "critical"
    if p >= 0.6:
        return "high"
    if p >= 0.35:
        return "medium"
    if p >= 0.15:
        return "low"
    return "none"


def harvest_deadline(days: list[RouteDay], lead_hours: int, block_at: float = 0.6) -> date | None:
    """Last safe day to load: the day before the first day at or above `block_at`, minus the farmer's
    harvest lead time. None when no such day appears in the horizon."""
    for rd in days:
        if rd.p_disruption >= block_at:
            return rd.day - timedelta(days=1 + max(0, (lead_hours - 1) // 24))
    return None
