"""Load packages/shared/crops.json into crop_stages (idempotent). Usage: uv run python scripts/seed_crops.py"""
import _bootstrap  # noqa: F401
from sqlalchemy.dialects.postgresql import insert

from app.core.db import session_scope
from app.models.tables import CropStage
from app.services.models.phenology import crop_table

with session_scope() as db:
    table = crop_table()
    n = 0
    for crop, info in table["crops"].items():
        th = info.get("thresholds", {})
        for i, st in enumerate(info["phenology"]["stages"]):
            src = table.get("sources", {}).get(st.get("source_id") or "", {})
            vals = {"ord": i, "method": info["phenology"]["method"], "labels": st["label"], "thresholds": th.get(st["key"], {}),
                    "source": src, "version": table["version"],
                    "start_val": float(st["start"]) if isinstance(st["start"], int | float) else None,
                    "end_val": float(st["end"]) if isinstance(st["end"], int | float) else None}
            stmt = insert(CropStage).values(crop=crop, stage=st["key"], **vals)
            db.execute(stmt.on_conflict_do_update(index_elements=["crop", "stage"], set_=vals))
            n += 1
    print(f"crop_stages upserted: {n}")
