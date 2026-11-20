"""Explicit public journal schemas without owner or generation instructions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JournalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    schema_version: Literal["1"] = "1"
    run_id: UUID
    stage_id: UUID
    run_revision: int = Field(strict=True, ge=1)


class JournalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StageRead(JournalRead):
    id: UUID
    name: str
    objective: str
    duration_days: int
    starts_at: datetime
    ends_at: datetime


class RunRead(JournalRead):
    id: UUID
    template_id: UUID
    template_version: int
    revision: int
    name: str
    purpose: str
    short_description: str | None = None
    timezone: str
    status: Literal["active", "paused", "completed", "closed"]
    stages: tuple[StageRead, ...]
    current_stage_id: UUID | None
    capture_reference: JournalReference | None


class RunPage(JournalRead):
    enabled: bool
    items: tuple[RunRead, ...]
    total: int
    offset: int


class ActiveRun(JournalRead):
    enabled: bool
    run: RunRead | None


class EntryRead(JournalRead):
    resource_kind: Literal["document", "audio"]
    resource_id: UUID
    reference: JournalReference
    accepted_at: datetime


class EntryPage(JournalRead):
    items: tuple[EntryRead, ...]
    total: int
    offset: int
    run_revision: int


class IntentionRead(JournalRead):
    revision: int
    text: str | None
    recorded_at: datetime


class IntentionState(JournalRead):
    run_revision: int
    intention: IntentionRead | None


class IntentionPage(JournalRead):
    items: tuple[IntentionRead, ...]
    total: int
    offset: int
    run_revision: int


class IntentionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_revision: int = Field(strict=True, ge=1)
    text: str | None = Field(max_length=4000)

    @field_validator("text")
    @classmethod
    def visible_text(cls, value):
        if value is not None and (not value or value != value.strip()):
            raise ValueError("journal_invalid_intention")
        return value


class MutationRead(JournalRead):
    key: UUID
    run_id: UUID
    revision: int
    recorded_at: datetime


class InvitationJournalRead(JournalRead):
    reference: JournalReference
    run_name: str
    stage_name: str
    stage_objective: str
    purpose: str


class CurrentQuestion(JournalRead):
    invitation_id: UUID | None


class EntrySummary(JournalRead):
    diary: int = Field(ge=0)
    runs: dict[UUID, int]
    observed_at: datetime
