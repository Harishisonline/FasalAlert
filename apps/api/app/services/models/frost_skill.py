"""How well the shipped frost/heat classifier is shown to work at a given threshold, read from the
artifact's metrics.json (48 h, held-out seasons). PRD §9.1: fewer than 30 events means preliminary."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from app.services.models.frost import artifact_path

SkillStatus = Literal["demonstrated", "not_demonstrated", "preliminary", "not_evaluated"]
_RANK = {"demonstrated": 0, "not_demonstrated": 1, "preliminary": 2, "not_evaluated": 3}


@lru_cache(maxsize=1)
def _headline() -> dict[str, dict[float, dict[str, Any]]]:
    p = artifact_path().parent / "metrics.json"
    try:
        h = json.loads(p.read_text())["metrics"]["headline_48h_shipped"]
    except (OSError, KeyError, ValueError):
        return {}
    return {kind: {float(k.rstrip("C")): v for k, v in rows.items()} for kind, rows in h.items()}


def _status(row: dict[str, Any]) -> SkillStatus:
    if row.get("preliminary"):
        return "preliminary"
    lo = (row.get("bss_95ci") or [None])[0]
    return "demonstrated" if lo is not None and lo > 0 else "not_demonstrated"


def skill_for(kind: str, threshold_c: float) -> dict[str, Any]:
    """The worse status of the two evaluated thresholds that bracket `threshold_c`; outside them, not_evaluated."""
    rows = _headline().get(kind, {})
    if not rows or threshold_c < min(rows) or threshold_c > max(rows):
        return {"status": "not_evaluated", "evaluated_thresholds_c": sorted(rows)}
    lo = max(t for t in rows if t <= threshold_c)
    hi = min(t for t in rows if t >= threshold_c)
    worst = max((lo, hi), key=lambda t: _RANK[_status(rows[t])])
    r = rows[worst]
    return {"status": _status(r), "evaluated_threshold_c": worst, "n_events": r.get("n_events"),
            "bss_95ci": r.get("bss_95ci")}
