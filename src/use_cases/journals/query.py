"""Owner-scoped projections and context resolution without notes or graph access."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from src.core.journals.calendar import utc
from src.core.journals.contracts import (
    EntryReference,
    FreeQuestionContext,
    InvitationJournalView,
    administrative_run,
    public_run,
    question_context,
    validate_entry_reference,
)
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.core.journals.inventory import JournalInventory
from src.core.journals.ports import Journals
from src.use_cases.journals.manage import require_access


class QueryJournals:
    def __init__(
        self,
        repository: Journals,
        *,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
        inventory: JournalInventory | None = None,
    ):
        self.repository, self.enabled, self.clock = repository, enabled, clock
        self.inventory = inventory

    async def summary(self, owner: UUID):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
        if self.inventory is None:
            raise JournalStorageUnavailable()
        counts = await self.inventory.counts(owner)
        return dict(
            **counts.model_dump(),
            observed_at=utc(self.clock()) if self.clock else datetime.now(UTC),
        )

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

    async def list(self, owner: UUID, *, limit: int = 30, offset: int = 0):
        self._page(limit, offset)
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            now = utc(self.clock()) if self.clock else await transaction.now()
            runs, total = await transaction.runs(limit=limit, offset=offset)
            return dict(
                enabled=self.enabled,
                items=tuple(public_run(run, now) for run in runs),
                total=total,
                offset=offset,
            )

    async def active(self, owner: UUID):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.current()
            now = utc(self.clock()) if self.clock else await transaction.now()
            view = public_run(run, now) if run else None
            return dict(
                enabled=self.enabled,
                run=view if self.enabled and view and view.status == "active" else None,
            )

    async def entries(self, owner: UUID, run_id: UUID, *, limit: int = 30, offset: int = 0):
        return await self._page_for_run(owner, run_id, limit, offset, "entries")

    async def intentions(self, owner: UUID, run_id: UUID, *, limit: int = 20, offset: int = 0):
        return await self._page_for_run(owner, run_id, limit, offset, "intention_versions")

    async def _page_for_run(self, owner, identifier, limit, offset, method):
        self._page(limit, offset)
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.run(identifier)
            if run is None:
                raise JournalError("journal_not_found")
            items, total = await getattr(transaction, method)(
                identifier, limit=limit, offset=offset
            )
            return dict(items=items, total=total, offset=offset, run_revision=run.revision)

    async def invitation_context(self, owner: UUID, invitation_id: UUID):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            context = await transaction.response_context(invitation_id)
            if context.reference is None:
                return None
            ref = context.reference
            run = await transaction.run(ref.run_id, ref.run_revision)
            if run is None:
                raise JournalError("journal_not_found")
            stage = next((stage for stage in run.stages if stage.id == ref.stage_id), None)
            if stage is None:
                raise JournalError("journal_not_found")
            return InvitationJournalView(
                reference=ref,
                run_name=run.name,
                stage_name=stage.definition.name,
                stage_objective=stage.definition.objective,
                purpose=run.purpose,
            )

    @staticmethod
    def _page(limit, offset):
        if not 1 <= limit <= 100 or offset < 0 or offset > 100000:
            raise JournalError("journal_invalid_page")

    async def intention_state(self, owner: UUID, run_id: UUID):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.run(run_id)
            if run is None:
                raise JournalError("journal_not_found")
            return dict(run_revision=run.revision, intention=run.intention)

    async def latest_invitation(self, owner: UUID, run_id: UUID):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            run = await transaction.run(run_id)
            if run is None:
                raise JournalError("journal_not_found")
            now = utc(self.clock()) if self.clock else await transaction.now()
            if not self.enabled or public_run(run, now).status != "active":
                return {"invitation_id": None}
            return {"invitation_id": await transaction.latest_invitation(run_id, now)}
