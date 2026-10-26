"""Contracts for explicit, version-pinned historical analysis."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from src.core.extractors.personal_axes.history import HistoryRequest, HistorySource

__all__ = [
    "HistoryRequest",
    "HistorySource",
    "HistoryCandidates",
    "HistoryBatchView",
    "HistoryBatchPage",
]


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
