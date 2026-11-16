"""Deterministic phenology engine (PRD §9.6). Not ML, and inspectable by design.

Stage tables come from packages/shared/crops.json (every value cited in docs/CROP_PARAMETERS.md).
Three methods are supported, chosen per crop by the data file:
  gdd            stage boundaries in growing degree days after the season-start event
  calendar_days  stage boundaries in days after the season-start event
  calendar       stage boundaries as calendar dates "MM-DD" (perennial cycles keyed to the season)
The engine never guesses: with no season-start date the stage is unknown (PRD §7.4, AC 9).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from app.core.config import SHARED_DIR
from app.core.timeutil import today_ist

VERSION = "phenology-2026.11"
# Engine assumption (not a sourced threshold): an open-ended final stage (end = null in crops.json) lasts
# this long after it starts; past that the season is treated as complete and the farmer is asked for the
# new season-start date. Documented in docs/CROP_PARAMETERS.md and docs/MODEL_CARDS.md.
OPEN_STAGE_DAYS = 60


def stage_end(st: dict[str, Any], method: str) -> float:
    if st.get("end") is not None:
        return float(st["end"])
    if method == "gdd":
        return float(st["start"]) + OPEN_STAGE_DAYS * 15.0   # about 60 days at a typical 15 GDD per day
    return float(st["start"]) + OPEN_STAGE_DAYS


def season_length(crop: str) -> float:
    ph = crop_info(crop)["phenology"]
    return stage_end(ph["stages"][-1], ph["method"])


@lru_cache
def crop_table() -> dict[str, Any]:
    path = SHARED_DIR / "crops.json"
    return json.loads(path.read_text(encoding="utf-8"))


def crop_info(crop: str) -> dict[str, Any]:
    info = crop_table()["crops"].get(crop)
    if info is None:
        raise KeyError(f"unknown crop {crop}")
    return info


def source_for(source_id: str | None) -> dict[str, Any] | None:
    if not source_id:
        return None
    return crop_table().get("sources", {}).get(source_id)


def gdd_day(tmin: float, tmax: float, base: float, upper: float | None) -> float:
    """Simple averaging method (FAO-style): cap Tmax at the upper threshold, floor Tmin at base."""
    hi = min(tmax, upper) if upper is not None else tmax
    lo = max(tmin, base)
    hi = max(hi, lo)
    return max(0.0, (hi + lo) / 2.0 - base)


@dataclass
class StageResult:
    stage: str | None
    stage_label: dict[str, str] | None
    gdd_cum: float | None
    method: str | None
    next_stage: str | None
    next_stage_label: dict[str, str] | None
    next_stage_expected_on: date | None
    plus_minus_days: int | None
    explanation: dict[str, str] | None
    timeline: list[dict[str, Any]]
    thresholds: dict[str, Any]
    source_ids: list[str]

    def to_api(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "stage_label": self.stage_label,
            "gdd_cum": round(self.gdd_cum, 1) if self.gdd_cum is not None else None,
            "method": self.method, "next_stage": self.next_stage, "next_stage_label": self.next_stage_label,
            "next_stage_expected_on": self.next_stage_expected_on.isoformat() if self.next_stage_expected_on else None,
            "next_stage_plus_minus_days": self.plus_minus_days, "explanation": self.explanation,
            "timeline": self.timeline,
        }


def unknown_stage(crop: str) -> StageResult:
    info = crop_info(crop)
    label = info.get("season_start_label", {}).get("en", "sowing date").lower()
    return StageResult(None, None, None, None, None, None, None, None, {
        "en": f"Stage unknown. Add your {label} so the stage can be worked out.",
        "mr": "अवस्था माहित नाही. अवस्था ठरवण्यासाठी तारीख भरा.",
        "hi": "अवस्था ज्ञात नहीं. अवस्था तय करने के लिए तारीख भरें.",
    }, [], {}, [])


def _mmdd(s: str, year: int) -> date:
    m, d = (int(x) for x in s.split("-"))
    return date(year, m, min(d, 28) if m == 2 and d == 29 else d)


def _calendar_stage(stages: list[dict[str, Any]], today: date) -> tuple[int, date, date]:
    """Return (index, start, end) of the calendar stage containing today; stages may wrap the year."""
    for year in (today.year, today.year - 1):
        for i, st in enumerate(stages):
            a = _mmdd(st["start"], year)
            b = _mmdd(st["end"], year)
            if b < a:
                b = _mmdd(st["end"], year + 1)
            if a <= today <= b:
                return i, a, b
    raise LookupError("no calendar stage covers today")


def compute_stage(
    crop: str,
    season_start: date | None,
    daily: list[tuple[date, float | None, float | None]] | None = None,
    today: date | None = None,
    climatology_gdd_per_day: float | None = None,
) -> StageResult:
    """`daily` = (date, tmin, tmax) from season_start to yesterday, needed for the gdd method.
    `climatology_gdd_per_day` projects the next stage date when only history is known."""
    today = today or today_ist()
    info = crop_info(crop)
    ph = info["phenology"]
    stages: list[dict[str, Any]] = ph["stages"]
    method = ph["method"]
    thresholds_all = info.get("thresholds", {})
    unc = ph.get("uncertainty_days")

    if method == "calendar":
        idx, a, b = _calendar_stage(stages, today)
        cur, nxt = stages[idx], stages[(idx + 1) % len(stages)]
        expected = b + timedelta(days=1)
        expl = {
            "en": f"{cur['label']['en']} usually runs from {a:%d %b} to {b:%d %b} for this crop in Maharashtra.",
            "mr": f"महाराष्ट्रात या पिकाचा {cur['label']['mr']} साधारण {a:%d/%m} ते {b:%d/%m} असतो.",
            "hi": f"महाराष्ट्र में इस फसल का {cur['label']['hi']} आमतौर पर {a:%d/%m} से {b:%d/%m} तक होता है.",
        }
        timeline = [{"key": st["key"], "label": st["label"], "start": _mmdd(st["start"], today.year).isoformat(),
                     "end": _mmdd(st["end"], today.year).isoformat()} for st in stages]
        return StageResult(cur["key"], cur["label"], None, "calendar", nxt["key"], nxt["label"], expected, unc, expl,
                           timeline, thresholds_all.get(cur["key"], {}), [s for s in (cur.get("source_id"),) if s])

    if season_start is None:
        return unknown_stage(crop)
    if season_start > today:
        raise ValueError("season start in the future")

    if method == "calendar_days":
        value = float((today - season_start).days)
        unit_rate = 1.0
    elif method == "gdd":
        base = float(ph["base_temp_c"])
        upper = ph.get("upper_temp_c")
        if not daily:
            return StageResult(None, None, None, "gdd", None, None, None, None, {
                "en": "Temperature history is unavailable, so the stage cannot be worked out right now.",
                "mr": "तापमानाची माहिती उपलब्ध नसल्याने अवस्था ठरवता येत नाही.",
                "hi": "तापमान का इतिहास उपलब्ध नहीं है, इसलिए अवस्था तय नहीं हो सकती.",
            }, [], {}, [])
        value = sum(gdd_day(tn, tx, base, upper) for _, tn, tx in daily if tn is not None and tx is not None)
        recent = [gdd_day(tn, tx, base, upper) for _, tn, tx in daily[-14:] if tn is not None and tx is not None]
        unit_rate = climatology_gdd_per_day or (sum(recent) / len(recent) if recent else None) or 1.0
    else:
        raise ValueError(f"unsupported phenology method {method}")

    idx = 0
    for i, st in enumerate(stages):
        if value >= float(st["start"]):
            idx = i
    cur = stages[idx]
    nxt = stages[idx + 1] if idx + 1 < len(stages) else None
    expected = None
    if nxt is not None and unit_rate > 0:
        expected = today + timedelta(days=max(0, round((float(nxt["start"]) - value) / unit_rate)))
    past_end = value > stage_end(stages[-1], method)

    def to_date(v: float) -> date:
        return season_start + timedelta(days=round(v if method == "calendar_days" else v / unit_rate))

    timeline = [{"key": st["key"], "label": st["label"], "start": to_date(float(st["start"])).isoformat(),
                 "end": to_date(stage_end(st, method)).isoformat()} for st in stages]
    start_lbl = info.get("season_start_label", {"en": "Season start", "mr": "हंगाम सुरुवात", "hi": "मौसम की शुरुआत"})
    if method == "gdd":
        expl = {
            "en": f"{start_lbl['en']} {season_start:%d %b %Y}. {value:.0f} growing degree days so far "
                  f"(base {ph['base_temp_c']} °C). {cur['label']['en']} starts at {float(cur['start']):.0f}.",
            "mr": f"{start_lbl['mr']} {season_start:%d/%m/%Y}. आतापर्यंत {value:.0f} वाढ अंश दिवस "
                  f"(मूळ तापमान {ph['base_temp_c']} °C). {cur['label']['mr']} {float(cur['start']):.0f} पासून.",
            "hi": f"{start_lbl['hi']} {season_start:%d/%m/%Y}. अब तक {value:.0f} वृद्धि डिग्री दिन "
                  f"(आधार तापमान {ph['base_temp_c']} °C). {cur['label']['hi']} {float(cur['start']):.0f} से.",
        }
    else:
        expl = {
            "en": f"{start_lbl['en']} {season_start:%d %b %Y}: {value:.0f} days ago. "
                  f"{cur['label']['en']} is from day {float(cur['start']):.0f} to {stage_end(cur, method):.0f}.",
            "mr": f"{start_lbl['mr']} {season_start:%d/%m/%Y}: {value:.0f} दिवसांपूर्वी. "
                  f"{cur['label']['mr']} दिवस {float(cur['start']):.0f} ते {stage_end(cur, method):.0f}.",
            "hi": f"{start_lbl['hi']} {season_start:%d/%m/%Y}: {value:.0f} दिन पहले. "
                  f"{cur['label']['hi']} दिन {float(cur['start']):.0f} से {stage_end(cur, method):.0f}.",
        }
    if past_end:
        for k in expl:
            expl[k] += {"en": " The season looks complete; update the date for the new season.",
                        "mr": " हंगाम पूर्ण झाल्यासारखा दिसतो; नवीन हंगामाची तारीख भरा.",
                        "hi": " मौसम पूरा लगता है; नए मौसम की तारीख भरें."}[k]
    return StageResult(
        cur["key"], cur["label"], value if method == "gdd" else None, method,
        nxt["key"] if nxt else None, nxt["label"] if nxt else None, expected, unc, expl, timeline,
        thresholds_all.get(cur["key"], {}), [s for s in (cur.get("source_id"),) if s],
    )


def stage_thresholds(crop: str, stage: str | None) -> dict[str, Any]:
    if stage is None:
        return {}
    return crop_info(crop).get("thresholds", {}).get(stage, {})
