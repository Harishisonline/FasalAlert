"""Sync model artifacts and rule-based components into model_registry (PRD §8.3, AC 6)."""
import _bootstrap  # noqa: F401

from app.core.db import session_scope
from app.services.models.registry import register_static, sync_from_artifacts

with session_scope() as db:
    n = sync_from_artifacts(db)
    register_static(db)
    print(f"artifacts registered: {n}; static components registered: rain, transport, phenology")
