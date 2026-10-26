"""Aggregate evidence returned by storage without private account or document data."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class SummaryFacts:
    now: datetime
    users_total: int
    users_active: int
    accesses: int | None
    writers: int | None
    total_notes: int | None
    counts: dict[str, int]
    processing: dict[str, int]
    since: datetime | None
    complete: bool
    synced: datetime | None
    notes_complete: bool


@dataclass(frozen=True)
class ActivityFacts:
    now: datetime
    since: datetime | None
    notes_complete: bool
    accessed: dict[date, int]
    writers: dict[date, int]
