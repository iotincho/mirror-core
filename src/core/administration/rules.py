"""Period boundaries and uncertainty-aware dashboard projection."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.core.administration.models import (
    ActivityPoint,
    ActivitySeries,
    Coverage,
    DashboardSummary,
    ProcessingCounts,
    Sources,
)

ZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def period_start(now, days):
    today = now.astimezone(ZONE).date()
    first = today - timedelta(days=days - 1)
    return datetime.combine(first, datetime.min.time(), ZONE).astimezone(UTC)


def dashboard_summary(facts, days):
    return DashboardSummary(
        period_days=days,
        updated_at=facts.now,
        users_total=facts.users_total,
        users_active=facts.users_active,
        users_accessed=facts.accesses,
        users_wrote=facts.writers,
        notes_total=facts.total_notes,
        notes_created=facts.counts.get("writing", 0) + facts.counts.get("audio", 0)
        if facts.notes_complete
        else None,
        notes_by_source=Sources(
            **{
                kind: facts.counts.get(kind, 0) if facts.notes_complete else None
                for kind in ("writing", "audio", "imported")
            }
        ),
        processing=ProcessingCounts(
            completed=facts.processing.get("completed", 0),
            failed=facts.processing.get("failed", 0),
            pending=sum(
                facts.processing.get(status, 0) for status in ("queued", "waiting", "retrying")
            ),
            running=facts.processing.get("running", 0),
        ),
        coverage=Coverage(
            activity_since=facts.since,
            documents_complete=facts.complete,
            inventory_synced_at=facts.synced,
            notes_complete=facts.notes_complete,
        ),
    )


def activity_series(facts, days):
    first = period_start(facts.now, days).astimezone(ZONE).date()
    return ActivitySeries(
        items=[
            ActivityPoint(
                date=day,
                accessed=facts.accessed.get(day, 0)
                if facts.since and day >= facts.since.astimezone(ZONE).date()
                else None,
                wrote=facts.writers.get(day, 0) if facts.notes_complete else None,
            )
            for day in (first + timedelta(days=index) for index in range(days))
        ]
    )
