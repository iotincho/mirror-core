from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_LIFETIME_DAYS = 15


class NotificationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[
        "open_invitation",
        "open_capture",
        "open_material",
        "open_install_help",
        "open_invitation_settings",
    ]
    invitation_id: UUID | None = None

    @model_validator(mode="after")
    def invitation_target(self):
        if (self.type == "open_invitation") != (self.invitation_id is not None):
            raise ValueError("Only open_invitation requires invitation_id")
        return self


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: Literal["announcement", "onboarding", "invitation"]
    title: str
    summary: str
    body: str
    action: NotificationAction | None
    published_at: datetime
    expires_at: datetime
    read_at: datetime | None
    completed: bool = False


class NotificationList(BaseModel):
    items: list[NotificationRead]
    next_cursor: str | None
    unread_count: int
    through: datetime


class ReadAll(BaseModel):
    through: datetime

    @model_validator(mode="after")
    def timezone_required(self):
        if self.through.tzinfo is None:
            raise ValueError("through requires a timezone")
        return self


class AnnouncementContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    body: str = Field(min_length=1, max_length=10000)
    action: NotificationAction | None = None
    lifetime_days: int = Field(default=DEFAULT_LIFETIME_DAYS, ge=1, le=365)

    @model_validator(mode="after")
    def shared_action(self):
        if self.action and self.action.type == "open_invitation":
            raise ValueError("An announcement cannot target a user's private invitation")
        return self
