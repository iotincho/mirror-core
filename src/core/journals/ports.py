"""Owner-scoped durable journals; transaction state never exposes an ORM session."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from src.core.journals.contracts import EntryReference, JournalEntryView, ResponseJournalContext
from src.core.journals.models import (
    Instant,
    IntentionVersion,
    JournalModel,
    JournalRun,
    JournalTemplate,
    Revision,
)

Operation = Literal["activate", "adjust", "pause", "resume", "advance", "close", "intention"]


class CaptureReferences(Protocol):
    async def resolve(
        self,
        owner: UUID,
        supplied: EntryReference | None,
        *,
        invitation_id: UUID | None = None,
    ) -> EntryReference | None: ...


class OwnerAccess(JournalModel):
    exists: bool
    enabled: bool
    workspace_active: bool


class MutationReceipt(JournalModel):
    key: UUID
    owner_id: UUID
    operation: Operation
    request_hash: str
    run_id: UUID
    revision: Revision
    recorded_at: Instant


class JournalTransaction(Protocol):
    async def access(self) -> OwnerAccess: ...
    async def lock_owner(self) -> None: ...
    async def now(self) -> datetime: ...
    async def receipt(self, key: UUID) -> MutationReceipt | None: ...
    async def template(self, identifier: UUID, version: int) -> JournalTemplate | None: ...
    async def current(self) -> JournalRun | None: ...
    async def run(self, identifier: UUID, revision: int | None = None) -> JournalRun | None: ...
    async def runs(self, *, limit: int, offset: int) -> tuple[tuple[JournalRun, ...], int]: ...
    async def revisions(
        self, identifier: UUID, *, limit: int, offset: int
    ) -> tuple[tuple[JournalRun, ...], int]: ...
    async def latest_invitation(self, identifier: UUID, at: datetime) -> UUID | None: ...
    async def entries(
        self, identifier: UUID, *, limit: int, offset: int
    ) -> tuple[tuple[JournalEntryView, ...], int]: ...
    async def intention_versions(
        self, identifier: UUID, *, limit: int, offset: int
    ) -> tuple[tuple[IntentionVersion, ...], int]: ...
    async def save(self, run: JournalRun, *, expected_revision: int | None) -> None: ...
    async def record_receipt(self, receipt: MutationReceipt) -> None: ...
    async def response_context(self, invitation_id: UUID) -> ResponseJournalContext: ...


class Journals(Protocol):
    def transaction(self, owner: UUID) -> AbstractAsyncContextManager[JournalTransaction]: ...
    async def install_template(self, template: JournalTemplate) -> None: ...
    async def templates(self, limit: int = 50) -> tuple[JournalTemplate, ...]: ...
    async def due_owners(self, *, at: datetime | None, limit: int) -> tuple[UUID, ...]: ...
