"""All user-facing dates are IST (Asia/Kolkata)."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def ist_midnight(d: date | None = None) -> datetime:
    return datetime.combine(d or today_ist(), time(0, 0), tzinfo=IST)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(IST).isoformat(timespec="seconds") if dt else None
