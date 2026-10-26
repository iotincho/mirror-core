"""Explicit local-time policies; all operational instants are UTC."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def scheduled_at(day: date, local_time: str, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    wall = datetime.combine(day, time.fromisoformat(local_time))
    # A round trip detects nonexistent wall times. Advance to the first valid minute.
    for _ in range(24 * 60 + 1):
        candidate = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == wall:
            return candidate
        wall += timedelta(minutes=1)
    raise ValueError("unresolvable_local_date")


def next_occurrence(now: datetime, local_time: str, timezone: str) -> datetime:
    day = now.astimezone(ZoneInfo(timezone)).date()
    candidate = scheduled_at(day, local_time, timezone)
    if candidate <= now:
        candidate = scheduled_at(day + timedelta(days=1), local_time, timezone)
    return candidate


def expires_at(due: datetime, timezone: str) -> datetime:
    day = due.astimezone(ZoneInfo(timezone)).date()
    midnight = scheduled_at(day + timedelta(days=1), "00:00", timezone)
    return min(due + timedelta(hours=2), midnight)
