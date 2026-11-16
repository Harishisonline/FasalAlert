"""PRD §16 day 4: stage boundaries for all 6 crops at 3 dates each, against packages/shared/crops.json."""
from datetime import date, timedelta

import pytest

from app.services.models import phenology as ph

CROPS = ["mango", "pomegranate", "grape", "soybean", "cotton", "sugarcane"]


def _daily(start: date, days: int, tmin=20.0, tmax=32.0):
    return [(start + timedelta(days=i), tmin, tmax) for i in range(days)]


@pytest.mark.parametrize("crop", CROPS)
def test_three_dates_per_crop_follow_the_table(crop):
    info = ph.crop_info(crop)
    stages = info["phenology"]["stages"]
    method = info["phenology"]["method"]
    start = date(2025, 6, 1)
    gdd_per_day = ph.gdd_day(20.0, 32.0, float(info["phenology"].get("base_temp_c") or 10), info["phenology"].get("upper_temp_c"))
    # three probe points: inside the first stage, inside a middle stage, inside the last stage
    picks = [stages[0], stages[len(stages) // 2], stages[-1]]
    for st in picks:
        a, b = float(st["start"]), ph.stage_end(st, method)
        mid = (a + b) / 2
        days = int(mid / gdd_per_day) + 1 if method == "gdd" else int(mid)
        today = start + timedelta(days=days)
        res = ph.compute_stage(crop, start, _daily(start, days) if method == "gdd" else None, today=today)
        assert res.stage == st["key"], (crop, st["key"], res.stage, days)
        assert res.explanation and res.explanation["en"] and res.explanation["mr"]
        assert len(res.timeline) == len(stages)


@pytest.mark.parametrize("crop", CROPS)
def test_unknown_without_season_start(crop):
    res = ph.compute_stage(crop, None)
    assert res.stage is None and "Stage unknown" in res.explanation["en"]


def test_gdd_formula_clamps_at_base():
    assert ph.gdd_day(5.0, 9.0, 10.0, None) == 0.0
    assert ph.gdd_day(20.0, 30.0, 10.0, None) == 15.0


def test_future_season_start_rejected():
    with pytest.raises(ValueError):
        ph.compute_stage("cotton", date.today() + timedelta(days=5), today=date.today())


def test_all_values_carry_sources_or_null():
    t = ph.crop_table()
    for crop in CROPS:
        info = t["crops"][crop]
        assert info["verified"] is False  # agronomist sign-off pending, stated in docs/CROP_PARAMETERS.md
        for st in info["phenology"]["stages"]:
            assert st.get("source_id") in t["sources"], (crop, st["key"])
