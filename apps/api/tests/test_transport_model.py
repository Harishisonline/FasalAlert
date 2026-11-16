from datetime import date, timedelta

from app.services.models import transport as tm

D0 = date(2026, 7, 10)


def seg(rain, cls="village", low=True, slope=1.0):
    return tm.SegmentInput(1, cls, slope, low, {D0 - timedelta(days=i): r for i, r in enumerate(rain)})


def test_dry_route_is_low():
    r = tm.susceptibility(seg([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), D0)
    assert r.score < 0.05 and tm.level(r.score) == "none"


def test_heavy_rain_on_low_lying_village_road_is_high():
    r = tm.susceptibility(seg([90, 40, 20, 30, 30, 20, 10, 10, 5, 5]), D0)
    assert r.score >= 0.8


def test_class_and_terrain_order():
    wet = [60, 30, 10, 20, 20, 20, 10, 10, 0, 0]
    nat = tm.susceptibility(seg(wet, "national", low=False), D0).score
    vil = tm.susceptibility(seg(wet, "village", low=True), D0).score
    assert vil > nat


def test_deadline_is_before_first_blocked_day():
    days = [tm.RouteDay(D0 + timedelta(days=i), p, 0, 1) for i, p in enumerate([0.1, 0.2, 0.7, 0.9])]
    assert tm.harvest_deadline(days, 24) == D0 + timedelta(days=1)
    assert tm.harvest_deadline(days[:2], 24) is None
    assert "not from observed closures" in tm.NOTE
