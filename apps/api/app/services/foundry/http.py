"""Shared HTTP plumbing for the data foundry: retries, timeouts, a polite User-Agent, ingest-run logging."""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import now_utc
from app.models.tables import IngestRun

log = logging.getLogger("fasalalert.foundry")

RETRY_STATUS = (429, 500, 502, 503, 504)


class UpstreamError(RuntimeError):
    """An upstream source failed after retries. Callers degrade the feature, not the page (PRD §13 rule 2)."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return False


def _wait_for(exc: BaseException, attempt: int) -> float:
    """How long to wait before the next attempt.

    Open-Meteo counts every location in a multi-point request against its per-minute quota, so a busy
    shared IP (a serverless function) can be answered with 429. The Retry-After header is the
    upstream's own instruction; the exponential fallback only applies when it is absent.
    """
    resp = getattr(exc, "response", None)
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return min(2 ** attempt, 15)


def client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": get_settings().http_user_agent}, follow_redirects=True)


def _request(method: str, url: str, params: dict[str, Any] | None, timeout: float, attempts: int,
             wait_budget: float, data: Any = None) -> httpx.Response:
    """One HTTP call with retries, bounded by a total wait budget.

    The budget matters on serverless: a request that sleeps past the function timeout is charged but
    produces nothing. Causal, degradable calls pass attempts=1 and wait_budget=0 to fail fast.
    """
    deadline = time.monotonic() + max(wait_budget, 0.0)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with client(timeout) as c:
                r = c.request(method, url, params=params, data=data)
                r.raise_for_status()
                return r
        except httpx.HTTPError as e:
            last = e
            if not _retryable(e) or attempt == attempts:
                raise
            wait = _wait_for(e, attempt)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            log.warning("%s %s failed (%s), retrying in %.1fs", method, url, type(e).__name__, min(wait, remaining))
            time.sleep(min(wait, remaining))
    raise last if last else UpstreamError(f"{url} failed")


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 30.0,
             attempts: int = 4, wait_budget: float = 20.0) -> Any:
    try:
        return _request("GET", url, params, timeout, attempts, wait_budget).json()
    except (httpx.HTTPError, ValueError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        raise UpstreamError(f"{url} failed ({status or type(e).__name__})") from e


def post_form(url: str, data: Any, timeout: float = 60.0, attempts: int = 3,
              wait_budget: float = 15.0) -> Any:
    try:
        return _request("POST", url, None, timeout, attempts, wait_budget, data=data).json()
    except (httpx.HTTPError, ValueError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        raise UpstreamError(f"{url} failed ({status or type(e).__name__})") from e


@contextmanager
def ingest_run(db: Session | None, source: str, **params: Any) -> Iterator[IngestRun]:
    """Record every ingestion attempt (provenance and job state). The run row is written in its own
    session so that a failure is still logged when the caller's transaction rolls back."""
    from app.core.db import SessionLocal

    log_db = SessionLocal()
    run = IngestRun(source=source, params=params, status="running")
    log_db.add(run)
    log_db.commit()
    try:
        yield run
        run.status = "ok" if run.status == "running" else run.status
    except Exception as e:
        run.status = "failed"
        run.error = str(e)[:500]
        raise
    finally:
        run.finished_at = now_utc()
        log_db.merge(run)
        log_db.commit()
        log_db.close()
