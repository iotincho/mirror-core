"""Durable state, leases, coordination and outbox without exposing ORM sessions."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from src.core.documents.ports import DocumentProjection, DocumentStore
from src.core.domain.audio_notes import AudioNote
from src.core.processing.models import OutboxDelivery, ProcessingJob


class ExecutionStore(Protocol):
    lease_seconds: int

    def resource_guard(self, processing_id: UUID) -> AbstractAsyncContextManager[bool]: ...

    async def acquire(
        self, processing_id: UUID, generation: int, owner: str
    ) -> ProcessingJob | None: ...

    async def assert_lease(self, record: ProcessingJob) -> None: ...

    async def heartbeat(self, record: ProcessingJob) -> None: ...

    async def advance(self, record: ProcessingJob, stage: str, checkpoints: dict) -> None: ...

    async def finish(
        self,
        record: ProcessingJob,
        *,
        status: str = "completed",
        error_code: str | None = None,
        retry_delay: float | None = None,
        retryable: bool = False,
    ) -> None: ...

    async def workspace_active(self, user_id: UUID) -> bool: ...

    async def extractor_children(self, parent_id: UUID, user_id: UUID) -> list[ProcessingJob]: ...

    async def extractors_and_wait(
        self, record: ProcessingJob, specifications: list[dict]
    ) -> None: ...

    async def child(self, record: ProcessingJob) -> ProcessingJob | None: ...

    async def child_and_wait(
        self, record: ProcessingJob, document_id: UUID, *, invitation_id: UUID | None = None
    ) -> None: ...


class OutboxStore(Protocol):
    async def claim_outbox(self, limit: int = 20) -> list[OutboxDelivery]: ...

    async def settle_outbox(self, row: OutboxDelivery, *, published: bool) -> None: ...


class ProcessingPublisher(Protocol):
    async def __call__(self, processing_id: str, generation: int) -> object:
        """Return after broker confirmation; at-least-once delivery may duplicate messages."""


class WorkflowContext(Protocol):
    record: ProcessingJob
    repository: ExecutionStore

    async def advance(self, stage: str, **checkpoints) -> None: ...

    async def assert_lease(self) -> None: ...


class WorkspaceIdentity(Protocol):
    user_id: UUID


class AudioOriginals(Protocol):
    async def create(self, note: AudioNote, content: bytes) -> None: ...

    async def get(self, identifier: UUID) -> AudioNote: ...

    async def restore_metadata(self, note: AudioNote) -> None: ...

    async def verify_original(self, note: AudioNote, *, size_bytes: int, sha256: str) -> None: ...


class ProcessingWorkspace(Protocol):
    context: WorkspaceIdentity
    document_store: DocumentStore
    graph_store: DocumentProjection
    audio_note_store: AudioOriginals


WorkspaceFactory = Callable[[UUID], AbstractAsyncContextManager[ProcessingWorkspace]]
