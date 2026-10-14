"""Public contracts omit endpoints, subscription keys and session identifiers."""

import re
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
