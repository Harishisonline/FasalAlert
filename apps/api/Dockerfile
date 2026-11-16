# FasalAlert API and worker image (Railway). Build context: apps/api, plus packages/shared copied in by the build step below.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
WORKDIR /srv/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/api/ ./
COPY packages/shared/ /srv/packages/shared/
ENV APP_ENV=production PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
# The API service runs migrations then serves; the worker service overrides CMD (see railway.worker.toml).
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
