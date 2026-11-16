"""Groq Chat Completions client (OpenAI-compatible). Keys are read from settings only — never logged."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

log = logging.getLogger("fasalalert.llm")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_enabled() -> bool:
    s = get_settings()
    return bool(s.groq_api_key and s.groq_api_key.strip())


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 450,
    timeout: float = 45.0,
) -> str | None:
    """Return the assistant message text, or None when Groq is unavailable / errors."""
    s = get_settings()
    key = (s.groq_api_key or "").strip()
    if not key:
        return None
    body: dict[str, Any] = {
        "model": s.groq_model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        # Qwen3 on Groq: keep reasoning off for fast, direct farm answers.
        "reasoning_effort": "none",
    }
    try:
        # trust_env=False: ignore HTTP(S)_PROXY so local Ask is not blocked by a corporate/mitm proxy.
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            r = client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
            if r.status_code == 429:
                # Per-minute token limit: wait as long as Groq asks (up to 10 s) and try once more.
                wait = _retry_after(r)
                if wait is not None and wait <= 10:
                    log.info("groq rate limited; retrying in %.1f s", wait)
                    time.sleep(wait)
                    r = client.post(
                        GROQ_URL,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json=body,
                    )
            if r.status_code >= 400:
                log.warning("groq chat failed status=%s", r.status_code)
                return None
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            msg = (choices[0].get("message") or {}).get("content")
            return msg.strip() if isinstance(msg, str) and msg.strip() else None
    except Exception:  # noqa: BLE001 - degrade to deterministic compose
        log.exception("groq chat request failed")
        return None


def _retry_after(r: httpx.Response) -> float | None:
    raw = r.headers.get("retry-after")
    try:
        return max(0.5, float(raw)) if raw is not None else None
    except ValueError:
        return None
