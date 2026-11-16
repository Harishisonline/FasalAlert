"""Shared HTTP plumbing for the data foundry: retries, timeouts, a polite User-Agent, ingest-run logging."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.timeutil import now_utc
from app.models.tables import IngestRun

log = logging.getLogger("fasalalert.foundry")


class UpstreamError(RuntimeError):
    """An upstream source failed after retries. Callers degrade the feature, not the page (PRD §13 rule 2)."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


def client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": get_settings().http_user_agent}, follow_redirects=True)


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20), reraise=True)
def _get(url: str, params: dict[str, Any] | None, timeout: float) -> httpx.Response:
    with client(timeout) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    try:
        return _get(url, params, timeout).json()
    except (httpx.HTTPError, ValueError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        raise UpstreamError(f"{url} failed ({status or type(e).__name__})") from e


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30), reraise=True)
def _post(url: str, data: Any, timeout: float) -> httpx.Response:
    with client(timeout) as c:
        r = c.post(url, data=data)
        r.raise_for_status()
        return r


def post_form(url: str, data: Any, timeout: float = 60.0) -> Any:
    try:
        return _post(url, data, timeout).json()
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
