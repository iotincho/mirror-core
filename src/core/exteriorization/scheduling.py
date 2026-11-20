"""Explicit local-time policies; all operational instants are UTC."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EVERY_DAY = (1, 2, 3, 4, 5, 6, 7)


def normalize_weekdays(days) -> list[int]:
    values = list(days)
    if not values or any(type(day) is not int or day not in EVERY_DAY for day in values):
        raise ValueError("weekdays must contain ISO weekdays from 1 to 7")
    if len(values) != len(set(values)):
        raise ValueError("weekdays must not contain duplicates")
    return sorted(values)


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


def next_occurrence(now: datetime, local_time: str, timezone: str, weekdays=EVERY_DAY) -> datetime:
    allowed = normalize_weekdays(weekdays)
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    # Two weeks cover a skipped local calendar date (for example, a timezone shift).
    for offset in range(15):
        day = today + timedelta(days=offset)
        if day.isoweekday() not in allowed:
            continue
        candidate = scheduled_at(day, local_time, timezone)
        if candidate > now and candidate.astimezone(zone).date() == day:
            return candidate
    raise ValueError("unresolvable_weekly_schedule")


def expires_at(due: datetime, timezone: str) -> datetime:
    day = due.astimezone(ZoneInfo(timezone)).date()
    midnight = scheduled_at(day + timedelta(days=1), "00:00", timezone)
    return min(due + timedelta(hours=2), midnight)
