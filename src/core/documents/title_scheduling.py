"""Read policy and durable scheduling boundary; no jobs, sessions or credentials."""

from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class TitleReadPolicy:
    limit: int
    enabled: bool


@dataclass(frozen=True)
class TitleBackfillResult:
    document_id: UUID
    status: str
    processing_id: UUID | None = None

    def serializable(self):
        return {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(self).items()
        }


class TitleScheduling(Protocol):
    owner: UUID

    async def unavailable(self, document_ids: list[UUID]) -> dict[UUID, TitleBackfillResult]: ...

    async def execute(
        self, document_id: UUID, *, apply: bool, retry_failed: bool
    ) -> TitleBackfillResult: ...
