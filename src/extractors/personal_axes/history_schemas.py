"""Contracts for explicit, version-pinned historical analysis."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class HistoryNote(BaseModel):
    document_id: UUID
    title: str
    date: datetime
    source_hash: str
    status: Literal["unanalysed", "current", "previous_version", "changed", "in_progress"]
    findings_count: int


class HistoryCandidates(BaseModel):
    version_id: UUID
    version_number: int
    total: int
    remaining: int
    items: list[HistoryNote]
    next_offset: int | None


class HistoryItemView(BaseModel):
    document_id: UUID
    title: str
    status: str
    retryable: bool


class HistoryBatchView(BaseModel):
    id: UUID
    axis_id: UUID
    version_id: UUID
    version_number: int
    created_at: datetime
    stopped_at: datetime | None
    status: str
    total: int
    finished: int
    counts: dict[str, int]
    retryable: int
    items: list[HistoryItemView]
    next_offset: int | None


class HistoryBatchPage(BaseModel):
    items: list[HistoryBatchView]
    next_offset: int | None
