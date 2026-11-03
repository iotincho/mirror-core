"""Typed application inputs/projections; HTTP schemas remain in access adapters."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator

from src.core.journals.calendar import utc
from src.core.journals.catalogs import catalog_for
from src.core.journals.errors import JournalError
from src.core.journals.models import (
    Instant,
    IntentionVersion,
    JournalModel,
    JournalRun,
    JournalStatus,
    Revision,
    ScheduledStage,
    StageCatalog,
    StageDefinition,
)
from src.core.journals.rules import effective_status, stage_at


class EntryReference(JournalModel):
    """Untrusted until resolved against an immutable snapshot for the owner."""

    schema_version: Literal["1"] = "1"
    run_id: UUID
    stage_id: UUID
    run_revision: Revision


class ResponseJournalContext(JournalModel):
    """Resolved from the owner's invitation; None reference denotes a free invitation."""

    reference: EntryReference | None = None


def validate_entry_reference(
    owner: UUID,
    supplied: EntryReference | None,
    archived_run: JournalRun | None,
    *,
    response: ResponseJournalContext | None = None,
) -> EntryReference | None:
    reference = supplied
    if response is not None:
        if supplied is not None and supplied != response.reference:
            raise JournalError("journal_reference_conflict")
        reference = response.reference
    if reference is None:
        return None
    if (
        archived_run is None
        or archived_run.owner_id != owner
        or archived_run.id != reference.run_id
        or archived_run.revision != reference.run_revision
        or not any(stage.id == reference.stage_id for stage in archived_run.stages)
    ):
        raise JournalError("journal_reference_not_found")
    return reference


class FreeQuestionContext(JournalModel):
    mode: Literal["free"] = "free"
    owner_id: UUID


class JournalQuestionContext(JournalModel):
    mode: Literal["journal"] = "journal"
    owner_id: UUID
    reference: EntryReference
    purpose: str = Field(repr=False)
    instructions: str = Field(repr=False)
    stage_objective: str = Field(repr=False)
    stage_instructions: str = Field(repr=False)
    intention: IntentionVersion | None = Field(default=None, repr=False)
    catalog: StageCatalog | None = Field(default=None, repr=False)


QuestionContext = FreeQuestionContext | JournalQuestionContext


class QuestionContextResolver(Protocol):
    async def resolve(self, owner: UUID, scheduled_at: datetime) -> QuestionContext:
        """Resolve an owner-scoped context for the occurrence, not the worker's clock."""
        ...


def question_context(owner: UUID, run: JournalRun | None, at: datetime) -> QuestionContext:
    at = utc(at)
    if run is None:
        return FreeQuestionContext(owner_id=owner)
    if run.owner_id != owner:
        raise JournalError("journal_not_found")
    stage = stage_at(run, at)
    if stage is None:
        return FreeQuestionContext(owner_id=owner)
    return JournalQuestionContext(
        owner_id=owner,
        reference=EntryReference(run_id=run.id, stage_id=stage.id, run_revision=run.revision),
        purpose=run.purpose,
        instructions=run.instructions,
        stage_objective=stage.definition.objective,
        stage_instructions=stage.definition.instructions,
        intention=run.intention,
        catalog=catalog_for(run, stage),
    )


class StageView(JournalModel):
    id: UUID
    name: str = Field(repr=False)
    objective: str = Field(repr=False)
    duration_days: int
    starts_at: Instant
    ends_at: Instant


class PublicRunView(JournalModel):
    id: UUID
    template_id: UUID
    template_version: Revision
    revision: Revision
    name: str = Field(repr=False)
    purpose: str = Field(repr=False)
    timezone: str
    status: JournalStatus
    stages: tuple[StageView, ...]
    current_stage_id: UUID | None
    capture_reference: EntryReference | None


def public_run(run: JournalRun, at: datetime) -> PublicRunView:
    stage = stage_at(run, at)
    return PublicRunView(
        id=run.id,
        template_id=run.template_id,
        template_version=run.template_version,
        revision=run.revision,
        name=run.name,
        purpose=run.purpose,
        timezone=run.timezone,
        status=effective_status(run, at),
        stages=tuple(
            StageView(
                id=item.id,
                name=item.definition.name,
                objective=item.definition.objective,
                duration_days=item.definition.duration_days,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
            )
            for item in run.stages
        ),
        current_stage_id=stage.id if stage else None,
        capture_reference=EntryReference(
            run_id=run.id,
            stage_id=stage.id,
            run_revision=run.revision,
        )
        if stage
        else None,
    )


class AdministrativeRunView(JournalModel):
    """Configuration only; no entries or personal intention, even after edits."""

    run: PublicRunView
    instructions: str = Field(repr=False)
    stages: tuple[ScheduledStage, ...]
    catalogs: tuple[StageCatalog, ...] = Field(default=(), repr=False)
    catalog_review_required: tuple[str, ...] = ()


def administrative_run(run: JournalRun, at: datetime) -> AdministrativeRunView:
    return AdministrativeRunView(
        run=public_run(run, at),
        instructions=run.instructions,
        stages=run.stages,
        catalogs=run.catalogs,
        catalog_review_required=tuple(
            stage.definition.key
            for stage in run.stages
            if run.status in {"active", "paused"}
            and stage.ends_at > (run.paused_at or at)
            and catalog_for(run, stage) is None
        ),
    )


class AdjustRun(JournalModel):
    expected_revision: Revision
    remaining_stages: tuple[StageDefinition, ...] = Field(min_length=1, max_length=52)
    purpose: str | None = Field(default=None, min_length=1, max_length=2000, repr=False)
    instructions: str | None = Field(default=None, max_length=4000, repr=False)
    catalogs: tuple[StageCatalog, ...] | None = Field(default=None, max_length=52, repr=False)


class ActivateRun(JournalModel):
    template_id: UUID
    template_version: Revision
    timezone: str

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value):
        return JournalRun.iana_timezone(value)


class ChangeLifecycle(JournalModel):
    expected_revision: Revision
    action: Literal["pause", "resume", "advance", "close"]


class EditIntention(JournalModel):
    expected_revision: Revision
    text: str | None = Field(max_length=4000, repr=False)
