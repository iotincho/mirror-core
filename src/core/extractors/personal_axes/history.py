"""Historical commands, detached facts and coverage policy."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.processing.models import ProcessingJob


class HistorySource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID
    documents: list[HistorySource] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_documents(self):
        if len({note.document_id for note in self.documents}) != len(self.documents):
            raise ValueError("duplicate_documents")
        return self


ACTIVE = ("queued", "running", "retrying", "waiting")
TERMINAL = {"completed", "skipped", "stopped", "changed", "deleted", "superseded", "failed"}


@dataclass
class HistoryBatch:
    id: UUID
    axis_id: UUID
    version_id: UUID
    request_hash: str
    created_at: datetime
    stopped_at: datetime | None


@dataclass
class HistoryItem:
    batch_id: UUID
    document_id: UUID
    source_hash: str
    processing_id: UUID | None = None
    outcome: str | None = None
    started_at: datetime | None = None


@dataclass
class HistoryView:
    batch: HistoryBatch
    version_number: int
    pairs: list[tuple[HistoryItem, ProcessingJob | None]]


@dataclass(frozen=True)
class HistoryStart:
    skip: bool
    outcome: str | None


def current_extraction(previous, version_id, source_hash, profile_hash):
    return bool(
        previous
        and previous["version_id"] == str(version_id)
        and previous["content_hash"] == source_hash
        and previous.get("profile_hash") == profile_hash
    )


def item_status(item, record):
    if item.outcome in {"current", "in_progress"}:
        return "skipped"
    if item.outcome:
        return item.outcome
    if record.resource_deleted:
        return "deleted"
    return record.status
