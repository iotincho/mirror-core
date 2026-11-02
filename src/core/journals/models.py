"""Immutable journal snapshots; no HTTP, storage or exteriorization dependency."""

from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.core.journals.calendar import utc

Instant = Annotated[AwareDatetime, AfterValidator(utc)]
Revision = Annotated[int, Field(strict=True, ge=1)]
Days = Annotated[int, Field(strict=True, ge=1, le=365)]
JournalStatus = Literal["active", "paused", "completed", "closed"]
JournalChange = Literal[
    "activation",
    "adjustment",
    "pause",
    "resume",
    "advance",
    "completion",
    "close",
    "intention",
]


class JournalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class StageDefinition(JournalModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120, repr=False)
    objective: str = Field(min_length=1, max_length=2000, repr=False)
    instructions: str = Field(default="", max_length=4000, repr=False)
    duration_days: Days

    @field_validator("name", "objective")
    @classmethod
    def visible_text(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("journal_invalid_text")
        return value


class JournalTemplate(JournalModel):
    id: UUID
    version: Revision
    name: str = Field(min_length=1, max_length=120, repr=False)
    purpose: str = Field(min_length=1, max_length=2000, repr=False)
    instructions: str = Field(default="", max_length=4000, repr=False)
    stages: tuple[StageDefinition, ...] = Field(min_length=1, max_length=52)

    @field_validator("name", "purpose")
    @classmethod
    def visible_text(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("journal_invalid_text")
        return value

    @model_validator(mode="after")
    def distinct_stages(self):
        if len({stage.key for stage in self.stages}) != len(self.stages):
            raise ValueError("journal_duplicate_stage")
        return self


class ScheduledStage(JournalModel):
    id: UUID
    definition: StageDefinition
    starts_at: Instant
    ends_at: Instant

    @model_validator(mode="after")
    def positive_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("journal_invalid_interval")
        return self


class IntentionVersion(JournalModel):
    revision: Revision
    text: str | None = Field(default=None, max_length=4000, repr=False)
    recorded_at: Instant

    @field_validator("text")
    @classmethod
    def nonblank_or_cleared(cls, value):
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("journal_invalid_intention")
        return value


class JournalRun(JournalModel):
    id: UUID
    owner_id: UUID
    template_id: UUID
    template_version: Revision
    revision: Revision
    name: str = Field(min_length=1, max_length=120, repr=False)
    purpose: str = Field(min_length=1, max_length=2000, repr=False)
    instructions: str = Field(default="", max_length=4000, repr=False)
    timezone: str
    status: JournalStatus = "active"
    change: JournalChange = "activation"
    origin: Literal["administration", "user", "calendar"] = "administration"
    started_at: Instant
    updated_at: Instant
    paused_at: Instant | None = None
    ended_at: Instant | None = None
    stages: tuple[ScheduledStage, ...] = Field(min_length=1, max_length=52)
    intention: IntentionVersion | None = Field(default=None, repr=False)

    @field_validator("name", "purpose")
    @classmethod
    def visible_text(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("journal_invalid_text")
        return value

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("journal_invalid_timezone") from None
        return value

    @model_validator(mode="after")
    def coherent_snapshot(self):
        expected_origin = {"intention": "user", "completion": "calendar"}.get(
            self.change, "administration"
        )
        if self.origin != expected_origin:
            raise ValueError("journal_invalid_change_origin")
        if self.updated_at < self.started_at or self.stages[0].starts_at != self.started_at:
            raise ValueError("journal_invalid_timeline")
        if len({stage.id for stage in self.stages}) != len(self.stages):
            raise ValueError("journal_duplicate_stage")
        if len({stage.definition.key for stage in self.stages}) != len(self.stages):
            raise ValueError("journal_duplicate_stage")
        if any(a.ends_at != b.starts_at for a, b in zip(self.stages, self.stages[1:])):
            raise ValueError("journal_noncontiguous_stages")
        if (self.status == "paused") != (self.paused_at is not None):
            raise ValueError("journal_invalid_pause")
        if self.paused_at is not None and not (
            self.started_at <= self.paused_at <= self.updated_at
            and self.paused_at < self.stages[-1].ends_at
        ):
            raise ValueError("journal_invalid_pause")
        if (self.status in {"closed", "completed"}) != (self.ended_at is not None):
            raise ValueError("journal_invalid_end")
        if self.ended_at is not None and not self.started_at <= self.ended_at <= self.updated_at:
            raise ValueError("journal_invalid_end")
        if self.status == "completed" and self.ended_at != self.stages[-1].ends_at:
            raise ValueError("journal_invalid_completion")
        if self.intention is not None and not (
            self.started_at <= self.intention.recorded_at <= self.updated_at
        ):
            raise ValueError("journal_invalid_intention_date")
        return self
