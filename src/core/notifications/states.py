"""Detached immutable publication payload with a durable mutable delivery cursor."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class AnnouncementState:
    key: str
    content: dict
    published_at: datetime
    expires_at: datetime
    last_user_id: UUID | None = None
    finished_at: datetime | None = None
