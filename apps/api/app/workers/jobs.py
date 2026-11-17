"""Background jobs (PRD §8.4 freshness contract). Each run is recorded in job_runs with an idempotency key,
so re-running a job for the same slot does nothing, and failures are logged with their error.

Run the worker as its own process (Railway service), never inside the Vercel frontend:
    uv run python -m app.workers.scheduler
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.timeutil import IST, now_ist, now_utc, today_ist
from app.models.tables import DecisionRow, Field, JobRun

log = logging.getLogger("fasalalert.jobs")


def run_job(job: str, run_key: str, fn: Callable[[Session], dict[str, Any]], retry_failed: bool = True) -> dict[str, Any] | None:
    """Claim (job, run_key) atomically; skip if a successful run exists; record the outcome.

    With retry_failed=False a failed slot is not claimed again: a refresh triggered by web traffic
    must not retry a rate-limited upstream on every request (the scheduled worker still retries it).
    """
    db = SessionLocal()
    try:
        values = {"job": job, "run_key": run_key, "status": "running"}
        if retry_failed:
            stmt = insert(JobRun).values(**values).on_conflict_do_update(
                index_elements=["job", "run_key"], set_={"status": "running", "attempts": JobRun.attempts + 1, "started_at": now_utc(), "error": None},
                where=JobRun.status == "failed")
        else:
            stmt = insert(JobRun).values(**values).on_conflict_do_nothing(index_elements=["job", "run_key"])
        res = db.execute(stmt.returning(JobRun.id))
        claimed = res.scalar_one_or_none()
        db.commit()
        if claimed is None:
            return None  # already ran (or is running) for this slot
        try:
            detail = fn(db)
            db.commit()
            status, err = "ok", None
        except Exception as e:  # noqa: BLE001 - every failure is recorded, then the scheduler moves on
            db.rollback()
            detail, status, err = {}, "failed", f"{type(e).__name__}: {e}"[:1000]
            log.error("job %s %s failed: %s\n%s", job, run_key, err, traceback.format_exc(limit=5))
        db.execute(JobRun.__table__.update().where(JobRun.id == claimed).values(
            status=status, finished_at=now_utc(), detail=detail or {}, error=err))
        db.commit()
        return detail
    finally:
        db.close()


def slot(hours: int) -> str:
    n = now_ist()
    return f"{n:%Y-%m-%d}T{(n.hour // hours) * hours:02d}"


# ---------------- job bodies ----------------
def refresh_forecasts(db: Session) -> dict[str, Any]:
    from app.services.foundry.http import UpstreamError
    from app.services.foundry.openmeteo import get_forecast

    ok = failed = 0
    for f in db.execute(select(Field)).scalars():
        try:
            get_forecast(db, f.lat, f.lon, field_id=f.id, force=True)
            ok += 1
        except UpstreamError:
            failed += 1
    return {"ok": ok, "failed": failed}


def recompute_decisions(db: Session) -> dict[str, Any]:
    from app.services.decision import engine
    from app.services.notify.alerts import create_alerts_for_decision

    n = alerts = errors = 0
    for f in db.execute(select(Field)).scalars().all():
        try:
            engine.compute(db, f)
            row = db.execute(select(DecisionRow).where(DecisionRow.field_id == f.id, DecisionRow.decision_date == today_ist())).scalar_one()
            alerts += len(create_alerts_for_decision(db, f, row))
            db.commit()
            n += 1
        except Exception:
            db.rollback()
            errors += 1
            log.exception("decision failed for field %s", f.id)
    return {"decisions": n, "alerts_created": alerts, "errors": errors}


def public_board(db: Session) -> dict[str, Any]:
    from app.services.decision.public_board import compute_board

    return {"districts": len(compute_board(db))}


def dispatch_alerts(db: Session) -> dict[str, Any]:
    from app.services.notify.alerts import dispatch_pending

    return dispatch_pending(db)


def market_ingest(db: Session) -> dict[str, Any]:
    from app.services.foundry.agmarknet import ingest_current
    from app.services.models.phenology import crop_table

    commodities = sorted({c["agmarknet_commodity"] for c in crop_table()["crops"].values() if c.get("agmarknet_commodity")})
    return {"result": ingest_current(db, commodities)}


def train_prices(db: Session) -> dict[str, Any]:
    from app.services.models.price import train_all

    return train_all(db)


def sync_registry(db: Session) -> dict[str, Any]:
    from app.services.models.registry import sync_from_artifacts

    return {"synced": sync_from_artifacts(db)}


JOBS: dict[str, tuple[Callable[[Session], dict[str, Any]], int]] = {
    # name: (function, slot length in hours)
    "refresh_forecasts": (refresh_forecasts, 3),
    "public_board": (public_board, 3),
    "recompute_decisions": (recompute_decisions, 6),
    "dispatch_alerts": (dispatch_alerts, 0),
    "market_ingest": (market_ingest, 24),
    "train_prices": (train_prices, 24 * 7),
    "sync_registry": (sync_registry, 24),
}


def run_named(name: str, retry_failed: bool = True) -> dict[str, Any] | None:
    fn, hours = JOBS[name]
    key = slot(hours) if hours else datetime.now(IST).strftime("%Y-%m-%dT%H:%M")
    return run_job(name, key, fn, retry_failed=retry_failed)


def refresh_public_board() -> dict[str, Any] | None:
    """Refresh the public board on web traffic.

    At most one attempt per hour, and a failed hour is not retried inside that hour: a burst of
    visitors must not become a burst of upstream weather calls, which are rate limited per IP. The
    scheduled worker runs the same job on its own 3-hour slot and still retries a failed one.
    """
    fn, _ = JOBS["public_board"]
    key = f"{datetime.now(IST):%Y-%m-%dT%H}h"   # hourly bucket, distinct from the worker's slot key
    return run_job("public_board", key, fn, retry_failed=False)
