"""Unique original identities, independently of transcription and processing state."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class OriginalEntry:
    kind: Literal["document", "audio"]
    id: UUID
    run_id: UUID | None = None
    audio_id: UUID | None = None
    document_id: UUID | None = None


class EntryCounts(BaseModel):
    diary: int = Field(ge=0)
    runs: dict[UUID, int]


class JournalInventory(Protocol):
    async def counts(self, owner: UUID) -> EntryCounts: ...


def count_originals(audio: Iterable[OriginalEntry], documents: Iterable[OriginalEntry]):
    """Audio and its derived documents represent one capture, even after reprocessing."""
    counts: dict[UUID | None, int] = {}
    audio_runs: dict[UUID, UUID | None] = {}
    derived: set[UUID] = set()
    for item in audio:
        audio_runs[item.id] = item.run_id
        counts[item.run_id] = counts.get(item.run_id, 0) + 1
        if item.document_id:
            derived.add(item.document_id)
    for item in documents:
        if item.id in derived:
            continue
        if item.audio_id:
            if item.audio_id in audio_runs:
                continue
            audio_runs[item.audio_id] = item.run_id
        counts[item.run_id] = counts.get(item.run_id, 0) + 1
    return EntryCounts(diary=counts.pop(None, 0), runs=counts)
