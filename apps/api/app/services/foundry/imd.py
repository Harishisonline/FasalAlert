"""IMD API (api.imd.gov.in): official warnings, agromet advisories and the NHAI highway nowcast.

Every IMD API endpoint returns 401 without a key (PRD §15). Registration is free at
https://api.imd.gov.in/public/register.php. The endpoint paths are given in IMD's API portal user guide
(https://api.imd.gov.in/public/IMD_API_Portal_User_Guide.pdf) and are configured through environment
variables, so nothing is called until both a key and a URL are set. When configured, the official
highway warning is preferred over the FasalAlert transport model (PRD §9.3).
"""
from __future__ import annotations

import os
from typing import Any

from app.core.config import get_settings
from app.services.foundry.http import UpstreamError, get_json


def _configured(url_env: str) -> str | None:
    url = os.environ.get(url_env, "")
    return url if (get_settings().imd_api_key and url) else None


def highway_warning(lat: float, lon: float) -> dict[str, Any] | None:
    url = _configured("IMD_HIGHWAY_WARNING_URL")
    if not url:
        return None
    try:
        data = get_json(url, {"lat": lat, "lon": lon, "key": get_settings().imd_api_key})
    except UpstreamError:
        return None
    if not data:
        return None
    item = data[0] if isinstance(data, list) else data
    text = item.get("warning") or item.get("message") or item.get("text")
    if not text:
        return None
    return {"text": str(text), "issued_at": str(item.get("issue_time") or item.get("issued_at") or ""),
            "source": "India Meteorological Department (NHAI highway nowcast)", "url": "https://api.imd.gov.in"}


def status() -> str:
    return "configured" if get_settings().imd_api_key else "not_configured"
