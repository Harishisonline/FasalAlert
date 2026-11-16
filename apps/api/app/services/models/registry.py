"""Model registry (PRD §8.3): the API never serves a model output without its registry row."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import API_ROOT, DATA_DIR
from app.core.timeutil import now_utc
from app.models.tables import ModelRegistry


def register(db: Session, *, name: str, version: str, kind: str, dataset_ref: str, metrics: dict[str, Any],
             thresholds: dict[str, Any], artifact_path: str, notes: str | None = None, trained_at: datetime | None = None) -> None:
    stmt = insert(ModelRegistry).values(name=name, version=version, kind=kind, dataset_ref=dataset_ref,
                                        trained_at=trained_at or now_utc(), metrics=metrics, thresholds=thresholds,
                                        artifact_path=artifact_path, notes=notes)
    stmt = stmt.on_conflict_do_update(index_elements=["name", "version"], set_={
        "kind": stmt.excluded.kind, "dataset_ref": stmt.excluded.dataset_ref, "trained_at": stmt.excluded.trained_at,
        "metrics": stmt.excluded.metrics, "thresholds": stmt.excluded.thresholds, "artifact_path": stmt.excluded.artifact_path,
        "notes": stmt.excluded.notes})
    db.execute(stmt)


def sync_from_artifacts(db: Session) -> int:
    """Register every data/artifacts/<name>/<version>/metrics.json whose artifact file exists (PRD AC 6)."""
    n = 0
    for mfile in sorted((DATA_DIR / "artifacts").glob("*/*/metrics.json")):
        m = json.loads(mfile.read_text())
        art = API_ROOT / m["artifact_path"]
        if not art.exists():
            continue
        register(db, name=m["name"], version=m["version"], kind=m["kind"], dataset_ref=m["dataset_ref"], metrics=m["metrics"],
                 thresholds=m.get("thresholds", {}), artifact_path=m["artifact_path"], notes=m.get("notes"),
                 trained_at=datetime.fromisoformat(m["trained_at"]))
        n += 1
    return n


def register_static(db: Session) -> None:
    """Rule-based components have registry rows too, so every served output is traceable."""
    from app.services.models import phenology, rain, transport

    register(db, name="rain", version=rain.VERSION, kind="ensemble_rule_uncalibrated",
             dataset_ref="Open-Meteo ensemble API, ECMWF IFS 0.25° 51 members, daily rain totals",
             metrics={"calibrated": False, "serving_status": "serving",
                      "note": "Member fraction, not a calibrated probability; no verification against IMD rain gauges yet"},
             thresholds={"imd_heavy_24h_mm": rain.IMD_HEAVY_24H_MM, "min_reported_probability": rain.MIN_REPORTED_P,
                         "horizon_days": rain.HORIZON_DAYS},
             artifact_path="app/services/models/rain.py", notes=rain.RULE)
    register(db, name="transport", version=transport.VERSION, kind="physical_rule_uncalibrated",
             dataset_ref="Open-Meteo forecast rainfall; OSM routes via OSRM; SRTM 30 m via OpenTopoData",
             metrics={"calibrated": False, "note": transport.NOTE, "serving_status": "serving"},
             thresholds={"imd_heavy_24h_mm": transport.IMD_HEAVY_24H, "imd_very_heavy_24h_mm": transport.IMD_VERY_HEAVY_24H,
                         "class_factor": transport.CLASS_FACTOR, "logistic_k": transport.LOGISTIC_K},
             artifact_path="app/services/models/transport.py", notes="Susceptibility score, not a closure forecast")
    register(db, name="phenology", version=phenology.VERSION, kind="deterministic",
             dataset_ref="packages/shared/crops.json (sources in docs/CROP_PARAMETERS.md)",
             metrics={"serving_status": "serving"}, thresholds={}, artifact_path="packages/shared/crops.json")
