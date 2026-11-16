"""PRD §13: one error envelope for every endpoint, with a greppable trace_id."""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("fasalalert")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")

STATUS = {
    "validation_error": 400,
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "rate_limited": 429,
    "data_stale": 503,
    "model_unavailable": 503,
    "internal_error": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status or STATUS.get(code, 400)


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}, "trace_id": trace_id_var.get()}}


def not_found(what: str = "Resource") -> ApiError:
    return ApiError("not_found", f"{what} does not exist")


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        tid = uuid.uuid4().hex[:8]
        trace_id_var.set(tid)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        # Never log bodies, tokens or OTPs: method, path and status only.
        log.info("%s %s %s trace=%s", request.method, request.url.path, response.status_code, tid)
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        headers = {}
        if exc.code == "rate_limited" and "retry_after" in exc.details:
            headers["Retry-After"] = str(int(exc.details["retry_after"]))
        return JSONResponse(envelope(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
        field = ".".join(loc) or None
        msg = first.get("msg", "Invalid input")
        return JSONResponse(envelope("validation_error", msg, {"field": field}), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(
            exc.status_code, "validation_error" if exc.status_code < 500 else "internal_error"
        )
        return JSONResponse(envelope(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error trace=%s", trace_id_var.get())
        # PRD §13 rule 1: never return a stack trace.
        return JSONResponse(envelope("internal_error", "Something went wrong on our side"), status_code=500)
