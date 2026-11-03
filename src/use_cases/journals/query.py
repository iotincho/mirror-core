"""Owner-scoped projections and context resolution without notes or graph access."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from src.core.journals.calendar import utc
from src.core.journals.contracts import (
    EntryReference,
    FreeQuestionContext,
    administrative_run,
    public_run,
    question_context,
    validate_entry_reference,
)
from src.core.journals.errors import JournalError
from src.core.journals.ports import Journals
from src.use_cases.journals.manage import require_access


class QueryJournals:
    def __init__(
        self,
        repository: Journals,
        *,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository, self.enabled, self.clock = repository, enabled, clock

    async def _view(self, owner, identifier, revision, administrative):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.run(identifier, revision)
            if run is None:
                raise JournalError("journal_not_found")
            now = utc(self.clock()) if self.clock else await transaction.now()
            # Historical projections refer to the recorded revision, not today's status.
            at = run.updated_at if revision is not None else now
            return administrative_run(run, at) if administrative else public_run(run, at)

    async def public(self, owner: UUID, run_id: UUID, revision: int | None = None):
        return await self._view(owner, run_id, revision, False)

    async def administrative(self, owner: UUID, run_id: UUID, revision: int | None = None):
        return await self._view(owner, run_id, revision, True)

    async def intention(self, owner: UUID, run_id: UUID, revision: int | None = None):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.run(run_id, revision)
            if run is None:
                raise JournalError("journal_not_found")
            return run.intention

    async def resolve(self, owner: UUID, scheduled_at: datetime):
        at = utc(scheduled_at)
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            context = question_context(owner, await transaction.current(), at)
            if not self.enabled and not isinstance(context, FreeQuestionContext):
                raise JournalError("journals_disabled")
            return context

    async def validate_reference(self, owner: UUID, reference: EntryReference):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            archived = await transaction.run(reference.run_id, reference.run_revision)
            return validate_entry_reference(owner, reference, archived)
