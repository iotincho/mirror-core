"""Owner-scoped durable journals; transaction state never exposes an ORM session."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from src.core.journals.models import Instant, JournalModel, JournalRun, JournalTemplate, Revision

Operation = Literal["activate", "adjust", "pause", "resume", "advance", "close", "intention"]


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
    async def save(self, run: JournalRun, *, expected_revision: int | None) -> None: ...
    async def record_receipt(self, receipt: MutationReceipt) -> None: ...


class Journals(Protocol):
    def transaction(self, owner: UUID) -> AbstractAsyncContextManager[JournalTransaction]: ...
    async def install_template(self, template: JournalTemplate) -> None: ...
    async def templates(self, limit: int = 50) -> tuple[JournalTemplate, ...]: ...
    async def due_owners(self, *, at: datetime | None, limit: int) -> tuple[UUID, ...]: ...
