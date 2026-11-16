"""FastAPI application. Run: uv run uvicorn app.main:app --reload (from apps/api)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.routers import ask_threads, auth_users, fields, market_transport, misc, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    settings.validate_for_startup()  # PRD §12: refuse to start with default secrets in production
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="FasalAlert API", version="0.1.0", lifespan=lifespan,
                  description="Microclimate decision engine for Maharashtra smallholders. Contract: PRD §11, packages/shared/api.ts.",
                  openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Accept-Language"])
    install_error_handlers(app)
    for r in (public.router, auth_users.router, fields.router, market_transport.router, ask_threads.router, misc.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
