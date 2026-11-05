"""Explicit LAN HTTP schemas. No original content or personal intention fields."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Positive = Annotated[int, Field(strict=True, ge=1)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Stage(Schema):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120, repr=False)
    objective: str = Field(min_length=1, max_length=2000, repr=False)
    instructions: str = Field(default="", max_length=4000, repr=False)
    duration_days: int = Field(strict=True, ge=1, le=365)


class Prompt(Schema):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    gentle: str = Field(min_length=1, max_length=240, repr=False)
    middle: str = Field(min_length=1, max_length=240, repr=False)
    deep: str = Field(min_length=1, max_length=240, repr=False)


class ReviewedCatalog(Schema):
    stage_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    prompts: tuple[Prompt, ...] = Field(min_length=1, max_length=12, repr=False)


class Catalog(ReviewedCatalog):
    goal_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Template(Schema):
    id: UUID
    version: Positive
    name: str = Field(repr=False)
    purpose: str = Field(repr=False)
    short_description: str | None = Field(
        default=None, max_length=160, repr=False, exclude_if=lambda value: value is None
    )
    instructions: str = Field(repr=False)
    stages: tuple[Stage, ...]
    catalogs: tuple[Catalog, ...]


class TemplateList(Schema):
    items: tuple[Template, ...]


class Activation(Schema):
    template_id: UUID
    template_version: Positive
    timezone: str = Field(min_length=1, max_length=100)


class Adjustment(Schema):
    expected_revision: Positive
    remaining_stages: tuple[Stage, ...] = Field(min_length=1, max_length=52)
    purpose: str | None = Field(default=None, min_length=1, max_length=2000, repr=False)
    instructions: str | None = Field(default=None, max_length=4000, repr=False)
    reviewed_catalogs: tuple[ReviewedCatalog, ...] = Field(default=(), max_length=52, repr=False)


class Lifecycle(Schema):
    expected_revision: Positive
    action: Literal["pause", "resume", "advance", "close"]


class StageView(Schema):
    id: UUID
    name: str = Field(repr=False)
    objective: str = Field(repr=False)
    duration_days: Positive
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class Run(Schema):
    id: UUID
    template_id: UUID
    template_version: Positive
    revision: Positive
    name: str = Field(repr=False)
    purpose: str = Field(repr=False)
    short_description: str | None = Field(
        default=None, max_length=160, repr=False, exclude_if=lambda value: value is None
    )
    timezone: str
    status: Literal["active", "paused", "completed", "closed"]
    stages: tuple[StageView, ...]
    current_stage_id: UUID | None


class ScheduledStage(Schema):
    id: UUID
    definition: Stage
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class Configuration(Schema):
    run: Run
    instructions: str = Field(repr=False)
    stages: tuple[ScheduledStage, ...]
    catalogs: tuple[Catalog, ...]
    catalog_review_required: tuple[str, ...]
    started_at: AwareDatetime
    updated_at: AwareDatetime
    paused_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    change: Literal[
        "activation", "adjustment", "pause", "resume", "advance", "completion", "close", "intention"
    ]
    origin: Literal["administration", "user", "calendar"]
    editable_stage_id: UUID | None


def configuration_response(value):
    return Configuration.model_validate(value.model_dump(exclude={"run": {"capture_reference"}}))


class Account(Schema):
    enabled: bool
    account_active: bool
    workspace_active: bool
    server_now: AwareDatetime
    items: tuple[Configuration, ...]
    total: int = Field(ge=0)


class Revision(Schema):
    revision: Positive
    updated_at: datetime
    change: str
    origin: Literal["administration", "user", "calendar"]


class History(Schema):
    items: tuple[Revision, ...]
    total: int = Field(ge=0)


class Receipt(Schema):
    key: UUID
    run_id: UUID
    revision: Positive
    operation: Literal["activate", "adjust", "pause", "resume", "advance", "close"]
    recorded_at: AwareDatetime


def receipt_response(value):
    return Receipt.model_validate(value.model_dump(exclude={"owner_id", "request_hash"}))
