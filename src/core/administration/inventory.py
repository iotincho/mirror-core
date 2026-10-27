"""Only identity, dates and provenance enter the administrative projection."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OriginalMetadata(BaseModel):
    id: UUID
    created_at: datetime
    source: str = Field(max_length=100)

    @field_validator("created_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("original date must include timezone")
        return value


def classify(source):
    if source in {"pwa_audio", "audio"}:
        return "audio"
    if source == "file_upload":
        return "imported"
    if source in {"pwa_note", "manual", "api", "note", "pwa"}:
        return "writing"
    return None


@dataclass(frozen=True)
class ReceiptMetadata:
    resource_id: UUID
    operation: str
    accepted_at: datetime
    resource_deleted: bool | None


@dataclass(frozen=True)
class InventoryEntry:
    document_id: UUID
    created_at: datetime
    arrived_at: datetime | None
    kind: str | None
    deleted: bool
