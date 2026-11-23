"""Bounded catch-up using the same pure calendar as foreground context reads."""

from collections.abc import Callable
from datetime import datetime

from src.core.journals.calendar import utc
from src.core.journals.models import JournalTemplate
from src.core.journals.ports import Journals
from src.core.journals.rules import reconcile


class InstallJournalTemplates:
    def __init__(self, repository: Journals):
        self.repository = repository

    async def execute(self, templates: tuple[JournalTemplate, ...]) -> None:
        for template in templates:
            await self.repository.install_template(template)


class ReconcileJournals:
    def __init__(self, repository: Journals, *, clock: Callable[[], datetime] | None = None):
        self.repository, self.clock = repository, clock

    async def execute(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("journal_invalid_batch_limit")
        at = utc(self.clock()) if self.clock else None
        count = 0
        for owner in await self.repository.due_owners(at=at, limit=limit):
            async with self.repository.transaction(owner) as transaction:
                if not (await transaction.access()).exists:
                    continue
                await transaction.lock_owner()
                run = await transaction.current()
                if run is None:
                    continue
                now = at if at is not None else await transaction.now()
                completed = reconcile(run, now=now)
                if completed is not run:
                    await transaction.save(completed, expected_revision=run.revision)
                    count += 1
        return count
