"""Calendar days in an explicit IANA zone; elapsed pause durations use UTC."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.core.journals.errors import JournalError


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise JournalError("journal_timezone_required")
    return value.astimezone(UTC)


def local_instant(wall: datetime, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    # Earlier fold for repeated times; first valid minute for a clock gap.
    for _ in range(48 * 60 + 1):
        instant = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            return instant
        wall += timedelta(minutes=1)
    raise JournalError("journal_unresolvable_calendar")


def first_end(start: datetime, days: int, timezone: str) -> datetime:
    day = utc(start).astimezone(ZoneInfo(timezone)).date() + timedelta(days=days)
    return local_instant(datetime.combine(day, time.min), timezone)


def shift_days(instant: datetime, days: int, timezone: str) -> datetime:
    wall = utc(instant).astimezone(ZoneInfo(timezone)).replace(tzinfo=None)
    return local_instant(wall + timedelta(days=days), timezone)
