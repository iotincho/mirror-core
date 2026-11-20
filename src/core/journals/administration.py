"""Administrative configuration contracts: no personal intention or original content."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from src.core.journals.contracts import AdministrativeRunView, administrative_run
from src.core.journals.models import (
    CatalogPrompt,
    Instant,
    JournalChange,
    JournalModel,
    JournalRun,
    Revision,
    StageDefinition,
)


class ReviewedCatalog(JournalModel):
    stage_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    prompts: tuple[CatalogPrompt, ...] = Field(min_length=1, max_length=12, repr=False)


class AdministrativeAdjustment(JournalModel):
    expected_revision: Revision
    remaining_stages: tuple[StageDefinition, ...] = Field(min_length=1, max_length=52)
    purpose: str | None = Field(default=None, min_length=1, max_length=2000, repr=False)
    instructions: str | None = Field(default=None, max_length=4000, repr=False)
    reviewed_catalogs: tuple[ReviewedCatalog, ...] = Field(default=(), max_length=52, repr=False)


class AdministrativeConfiguration(AdministrativeRunView):
    started_at: Instant
    updated_at: Instant
    paused_at: Instant | None
    ended_at: Instant | None
    change: JournalChange
    origin: Literal["administration", "user", "calendar"]
    editable_stage_id: UUID | None


def configuration(run: JournalRun, at) -> AdministrativeConfiguration:
    reference = run.paused_at or at
    editable = next((s.id for s in run.stages if s.starts_at <= reference < s.ends_at), None)
    return AdministrativeConfiguration(
        **administrative_run(run, at).model_dump(),
        started_at=run.started_at,
        updated_at=run.updated_at,
        paused_at=run.paused_at,
        ended_at=run.ended_at,
        change=run.change,
        origin=run.origin,
        editable_stage_id=editable if run.status in {"active", "paused"} else None,
    )
