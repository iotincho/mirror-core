"""Pure transitions returning new snapshots; callers retain previous revisions."""

from datetime import datetime
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.core.journals.calendar import first_end, shift_days, utc
from src.core.journals.catalogs import goal_hash
from src.core.journals.errors import JournalError
from src.core.journals.models import (
    IntentionVersion,
    JournalChange,
    JournalRun,
    JournalTemplate,
    ScheduledStage,
    StageCatalog,
    StageDefinition,
)


def stage_at(run: JournalRun, at: datetime) -> ScheduledStage | None:
    at = utc(at)
    if run.status != "active":
        return None
    return _scheduled_stage_at(run, at)


def _scheduled_stage_at(run: JournalRun, at: datetime) -> ScheduledStage | None:
    return next((stage for stage in run.stages if stage.starts_at <= at < stage.ends_at), None)


def effective_status(run: JournalRun, at: datetime) -> str:
    at = utc(at)
    if run.status == "active" and at >= run.stages[-1].ends_at:
        return "completed"
    return run.status


def ensure_no_active(owner: UUID, runs: tuple[JournalRun, ...], at: datetime) -> None:
    if any(run.owner_id == owner and effective_status(run, at) == "active" for run in runs):
        raise JournalError("journal_active_conflict")


def activate(
    template: JournalTemplate,
    *,
    run_id: UUID,
    owner: UUID,
    timezone: str,
    now: datetime,
    existing: tuple[JournalRun, ...] = (),
) -> JournalRun:
    now = utc(now)
    ensure_no_active(owner, existing, now)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise JournalError("journal_invalid_timezone") from None
    stages, start = [], now
    for position, definition in enumerate(template.stages):
        end = (
            first_end(start, definition.duration_days, timezone)
            if position == 0
            else shift_days(start, definition.duration_days, timezone)
        )
        stages.append(
            ScheduledStage(
                id=uuid5(run_id, definition.key),
                definition=definition,
                starts_at=start,
                ends_at=end,
            )
        )
        start = end
    return JournalRun(
        id=run_id,
        owner_id=owner,
        template_id=template.id,
        template_version=template.version,
        revision=1,
        name=template.name,
        purpose=template.purpose,
        short_description=template.short_description,
        instructions=template.instructions,
        timezone=timezone,
        catalogs=template.catalogs,
        started_at=now,
        updated_at=now,
        stages=tuple(stages),
    )


def require_revision(run: JournalRun, expected_revision: int, now: datetime) -> datetime:
    if run.revision != expected_revision:
        raise JournalError("journal_revision_conflict")
    now = utc(now)
    if now < run.updated_at:
        raise JournalError("journal_clock_regression")
    return now


def revised(run: JournalRun, now: datetime, *, change: JournalChange, **changes) -> JournalRun:
    # model_copy(update=...) skips Pydantic validation; validate the whole new snapshot.
    return JournalRun.model_validate(
        {
            **run.model_dump(),
            **changes,
            "revision": run.revision + 1,
            "updated_at": utc(now),
            "change": change,
            "origin": {"intention": "user", "completion": "calendar"}.get(change, "administration"),
        }
    )


def pause(run: JournalRun, *, expected_revision: int, now: datetime) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    if stage_at(run, now) is None:
        raise JournalError("journal_not_active")
    return revised(run, now, change="pause", status="paused", paused_at=now)


def resume(
    run: JournalRun,
    *,
    expected_revision: int,
    now: datetime,
    existing: tuple[JournalRun, ...] = (),
) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    if run.status != "paused":
        raise JournalError("journal_not_paused")
    ensure_no_active(run.owner_id, existing, now)
    delta = now - run.paused_at
    stages = tuple(
        ScheduledStage(
            id=stage.id,
            definition=stage.definition,
            starts_at=stage.starts_at + delta
            if stage.starts_at > run.paused_at
            else stage.starts_at,
            ends_at=stage.ends_at + delta if stage.ends_at > run.paused_at else stage.ends_at,
        )
        for stage in run.stages
    )
    return revised(run, now, change="resume", status="active", paused_at=None, stages=stages)


def reconcile(run: JournalRun, *, now: datetime) -> JournalRun:
    now = utc(now)
    if now < run.updated_at:
        raise JournalError("journal_clock_regression")
    if run.status == "active" and now >= run.stages[-1].ends_at:
        return revised(
            run, now, change="completion", status="completed", ended_at=run.stages[-1].ends_at
        )
    return run


def close(run: JournalRun, *, expected_revision: int, now: datetime) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    if effective_status(run, now) not in {"active", "paused"}:
        raise JournalError("journal_already_ended")
    return revised(run, now, change="close", status="closed", paused_at=None, ended_at=now)


def advance(run: JournalRun, *, expected_revision: int, now: datetime) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    current = stage_at(run, now)
    if current is None or now == current.starts_at:
        raise JournalError("journal_cannot_advance")
    position = run.stages.index(current)
    stages = list(run.stages[:position])
    stages.append(
        ScheduledStage(
            id=current.id,
            definition=current.definition,
            starts_at=current.starts_at,
            ends_at=now,
        )
    )
    start = now
    for stage in run.stages[position + 1 :]:
        end = shift_days(start, stage.definition.duration_days, run.timezone)
        stages.append(
            ScheduledStage(
                id=stage.id,
                definition=stage.definition,
                starts_at=start,
                ends_at=end,
            )
        )
        start = end
    terminal = position == len(run.stages) - 1
    return revised(
        run,
        now,
        change="advance",
        stages=tuple(stages),
        status="completed" if terminal else "active",
        ended_at=now if terminal else None,
    )


def adjust_remaining_stages(
    run: JournalRun,
    remaining: tuple[StageDefinition, ...],
    *,
    expected_revision: int,
    now: datetime,
    purpose: str | None = None,
    instructions: str | None = None,
    catalogs: tuple[StageCatalog, ...] | None = None,
    reviewed_catalogs: tuple[StageCatalog, ...] | None = None,
) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    effective_at = run.paused_at if run.status == "paused" else now
    current = _scheduled_stage_at(run, effective_at) if run.status in {"active", "paused"} else None
    if current is None:
        raise JournalError("journal_not_active")
    if not remaining or remaining[0].key != current.definition.key:
        raise JournalError("journal_current_stage_required")
    position = run.stages.index(current)
    completed = run.stages[:position]
    if {stage.definition.key for stage in completed} & {stage.key for stage in remaining}:
        raise JournalError("journal_completed_stage_immutable")
    known = {stage.definition.key: stage for stage in run.stages}
    stages, start = list(completed), current.starts_at
    for definition in remaining:
        previous = known.get(definition.key)
        if previous is not None and previous.starts_at == start:
            delta_days = definition.duration_days - previous.definition.duration_days
            end = (
                shift_days(previous.ends_at, delta_days, run.timezone)
                if delta_days
                else previous.ends_at
            )
        else:
            end = shift_days(start, definition.duration_days, run.timezone)
        if end <= effective_at:
            raise JournalError("journal_explicit_advance_required")
        stages.append(
            ScheduledStage(
                id=previous.id if previous else uuid5(run.id, definition.key),
                definition=definition,
                starts_at=start,
                ends_at=end,
            )
        )
        start = end
    retained = {stage.definition.key for stage in stages}
    selected_catalogs = (
        tuple(item for item in run.catalogs if item.stage_key in retained)
        if catalogs is None
        else catalogs
    )
    if catalogs is not None and reviewed_catalogs is not None:
        raise JournalError("journal_catalog_update_conflict")
    submitted = catalogs if catalogs is not None else reviewed_catalogs
    if submitted is not None:
        definitions = {stage.definition.key: stage.definition for stage in stages}
        old = {item.stage_key: item for item in run.catalogs}
        if len({item.stage_key for item in submitted}) != len(submitted):
            raise JournalError("journal_invalid_catalog_stage")
        for catalog in submitted:
            definition = definitions.get(catalog.stage_key)
            if definition is None or catalog.goal_hash != goal_hash(
                run.purpose if purpose is None else purpose,
                run.instructions if instructions is None else instructions,
                definition,
            ):
                raise JournalError("journal_catalog_review_required")
            previous = old.get(catalog.stage_key)
            if previous and {p.key for p in catalog.prompts} - {p.key for p in previous.prompts}:
                raise JournalError("journal_catalog_topic_identity_changed")
        if reviewed_catalogs is not None:
            merged = {item.stage_key: item for item in selected_catalogs}
            merged.update({item.stage_key: item for item in reviewed_catalogs})
            selected_catalogs = tuple(merged.values())
    return revised(
        run,
        now,
        change="adjustment",
        stages=tuple(stages),
        catalogs=selected_catalogs,
        purpose=run.purpose if purpose is None else purpose,
        instructions=run.instructions if instructions is None else instructions,
    )


def edit_intention(
    run: JournalRun,
    text: str | None,
    *,
    expected_revision: int,
    now: datetime,
) -> JournalRun:
    now = require_revision(run, expected_revision, now)
    if effective_status(run, now) not in {"active", "paused"}:
        raise JournalError("journal_already_ended")
    intention = IntentionVersion(
        revision=run.intention.revision + 1 if run.intention else 1,
        text=text,
        recorded_at=now,
    )
    return revised(run, now, change="intention", intention=intention)
