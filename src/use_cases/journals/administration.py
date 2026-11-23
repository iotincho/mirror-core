"""LAN configuration queries and previews, composed with the existing durable actions."""

from uuid import uuid4

from src.core.journals import rules
from src.core.journals.administration import AdministrativeAdjustment, configuration
from src.core.journals.catalogs import goal_hash
from src.core.journals.contracts import ActivateRun, AdjustRun, ChangeLifecycle
from src.core.journals.errors import JournalError
from src.core.journals.models import StageCatalog
from src.core.journals.ports import Journals
from src.use_cases.journals.manage import ManageJournals, require_access


class AdministerJournals:
    def __init__(self, repository: Journals, *, enabled: bool):
        self.repository, self.enabled = repository, enabled
        self.actions = ManageJournals(repository, enabled=enabled)

    async def templates(self):
        return await self.repository.templates(limit=100)

    async def account(self, owner, limit=20, offset=0):
        async with self.repository.transaction(owner) as tx:
            access = await tx.access()
            if not access.exists:
                raise JournalError("journal_owner_not_found")
            now = await tx.now()
            runs, total = await tx.runs(limit=limit, offset=offset)
            return dict(
                enabled=self.enabled,
                account_active=access.enabled,
                workspace_active=access.workspace_active,
                server_now=now,
                items=tuple(configuration(run, now) for run in runs),
                total=total,
            )

    async def detail(self, owner, identifier, revision=None):
        async with self.repository.transaction(owner) as tx:
            if not (await tx.access()).exists:
                raise JournalError("journal_owner_not_found")
            run = await tx.run(identifier, revision)
            if run is None:
                raise JournalError("journal_not_found")
            return configuration(run, run.updated_at if revision else await tx.now())

    async def history(self, owner, identifier, limit=20, offset=0):
        async with self.repository.transaction(owner) as tx:
            if not (await tx.access()).exists:
                raise JournalError("journal_owner_not_found")
            if await tx.run(identifier) is None:
                raise JournalError("journal_not_found")
            runs, total = await tx.revisions(identifier, limit=limit, offset=offset)
            return dict(
                items=tuple(
                    dict(
                        revision=r.revision,
                        updated_at=r.updated_at,
                        change=r.change,
                        origin=r.origin,
                    )
                    for r in runs
                ),
                total=total,
            )

    async def preview_activation(self, owner, command: ActivateRun):
        if not self.enabled:
            raise JournalError("journals_disabled")
        async with self.repository.transaction(owner) as tx:
            await require_access(tx)
            template = await tx.template(command.template_id, command.template_version)
            if template is None:
                raise JournalError("journal_template_not_found")
            now, current = await tx.now(), await tx.current()
            run = rules.activate(
                template,
                run_id=uuid4(),
                owner=owner,
                timezone=command.timezone,
                now=now,
                existing=(current,) if current else (),
            )
            return configuration(run, now)

    async def normalized(self, owner, identifier, command: AdministrativeAdjustment):
        async with self.repository.transaction(owner) as tx:
            await require_access(tx)
            # Pin normalization to the requested immutable revision, including on replay.
            run = await tx.run(identifier, command.expected_revision)
            if run is None:
                raise JournalError("journal_not_found")
            definitions = {s.key: s for s in command.remaining_stages}
            catalogs = []
            for item in command.reviewed_catalogs:
                if item.stage_key not in definitions:
                    raise JournalError("journal_catalog_review_required")
                catalogs.append(
                    StageCatalog(
                        stage_key=item.stage_key,
                        prompts=item.prompts,
                        goal_hash=goal_hash(
                            run.purpose if command.purpose is None else command.purpose,
                            run.instructions
                            if command.instructions is None
                            else command.instructions,
                            definitions[item.stage_key],
                        ),
                    )
                )
            return AdjustRun(
                expected_revision=command.expected_revision,
                remaining_stages=command.remaining_stages,
                purpose=command.purpose,
                instructions=command.instructions,
                reviewed_catalogs=tuple(catalogs) if catalogs else None,
            )

    async def preview(self, owner, identifier, command: AdministrativeAdjustment):
        if not self.enabled:
            raise JournalError("journals_disabled")
        normalized = await self.normalized(owner, identifier, command)
        async with self.repository.transaction(owner) as tx:
            await require_access(tx)
            run = await tx.run(identifier)
            if run is None:
                raise JournalError("journal_not_found")
            now = await tx.now()
            adjusted = rules.adjust_remaining_stages(
                run,
                normalized.remaining_stages,
                expected_revision=normalized.expected_revision,
                now=now,
                purpose=normalized.purpose,
                instructions=normalized.instructions,
                reviewed_catalogs=normalized.reviewed_catalogs,
            )
            return configuration(adjusted, now)

    async def activate(self, owner, command: ActivateRun, key):
        return await self.actions.activate(owner, command, key)

    async def adjust(self, owner, identifier, command: AdministrativeAdjustment, key):
        normalized = await self.normalized(owner, identifier, command)
        return await self.actions.adjust(owner, identifier, normalized, key)

    async def lifecycle(self, owner, identifier, command: ChangeLifecycle, key):
        return await self.actions.lifecycle(owner, identifier, command, key)
