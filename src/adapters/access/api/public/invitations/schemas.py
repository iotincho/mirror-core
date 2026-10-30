"""Public contracts omit endpoints, subscription keys and session identifiers."""

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    local_time: str = "20:30"
    timezone: str

    @field_validator("local_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("local_time must be HH:mm")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be an IANA zone") from None
        return value


class PreferenceRead(PreferenceUpdate):
    model_config = ConfigDict(from_attributes=True)
    next_due_at: datetime | None


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=1, max_length=200, repr=False)
    auth: str = Field(min_length=1, max_length=100, repr=False)


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=4096, repr=False)
    keys: SubscriptionKeys
    expirationTime: int | None = None


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    active: bool
    binding_id: UUID


class TestInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    candidate_id: str
    category: str
    question: str
    engine_version: str
    catalog_version: str
    kind: str
    local_date: date
    timezone: str
    scheduled_at: datetime
    expires_at: datetime
    created_at: datetime
    first_opened_at: datetime | None
    question_schema_version: Literal["1"]
    default_question_id: UUID
    question_groups: tuple["QuestionGroupRead", ...]
    available_question_ids: tuple[UUID, ...]


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    depth: Literal["gentle", "middle", "deep"] | None
    text: str


class QuestionGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: Literal["generic", "personalized"]
    layout: Literal["depths", "legacy"]
    questions: tuple[QuestionRead, ...]


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_question_id: UUID
    value: Literal["helpful", "unrelated", "not_now", "closed", "do_not_prompt"]


class FeedbackRead(FeedbackInput):
    id: UUID
    invitation_id: UUID
    recorded_at: datetime


class InteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    invitation_question_id: UUID
    kind: Literal["shown", "another_requested", "passed"]


class InteractionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: tuple[InteractionInput, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_events(self):
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("duplicate_interaction_event")
        return self


class InteractionsRead(BaseModel):
    recorded_event_ids: tuple[UUID, ...]


InvitationRead.model_rebuild()
