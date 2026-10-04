"""Timezone helpers. Everything the app stores is naive *clinic-local* time."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import TIMEZONE

TZ = ZoneInfo(TIMEZONE)


def now() -> datetime:
    """Current clinic-local time (naive)."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def combine(d: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute)


def human(dt: datetime | None, with_time: bool = True) -> str:
    if not dt:
        return "—"
    fmt = "%d %b %Y, %H:%M" if with_time else "%d %b %Y"
    return dt.strftime(fmt)


def ago(dt: datetime | None) -> str:
    if not dt:
        return "never"
    delta = now() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "scheduled"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"
