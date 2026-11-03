"""Serialize journal actions, immutable revisions and receipts in one unit of work."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from src.core.journals import rules
from src.core.journals.calendar import utc
from src.core.journals.contracts import ActivateRun, AdjustRun, ChangeLifecycle, EditIntention
from src.core.journals.errors import JournalError
from src.core.journals.ports import Journals, JournalTransaction, MutationReceipt, Operation


async def require_access(transaction: JournalTransaction) -> None:
    access = await transaction.access()
    if not access.exists:
        raise JournalError("journal_owner_not_found")
    if not access.enabled or not access.workspace_active:
        raise JournalError("journal_workspace_unavailable")


class ManageJournals:
    def __init__(
        self,
        repository: Journals,
        *,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository, self.enabled, self.clock = repository, enabled, clock

    async def activate(self, owner: UUID, command: ActivateRun, key: UUID) -> MutationReceipt:
        return await self._execute(owner, None, "activate", command, key)

    async def adjust(
        self,
        owner: UUID,
        run_id: UUID,
        command: AdjustRun,
        key: UUID,
    ) -> MutationReceipt:
        return await self._execute(owner, run_id, "adjust", command, key)

    async def lifecycle(
        self,
        owner: UUID,
        run_id: UUID,
        command: ChangeLifecycle,
        key: UUID,
    ) -> MutationReceipt:
        return await self._execute(owner, run_id, command.action, command, key)

    async def edit_intention(
        self,
        owner: UUID,
        run_id: UUID,
        command: EditIntention,
        key: UUID,
    ) -> MutationReceipt:
        return await self._execute(owner, run_id, "intention", command, key)

    async def _execute(self, owner, run_id, operation: Operation, command, key):
        digest = hashlib.sha256(
            json.dumps(
                {
                    "version": "journal-mutation/1",
                    "operation": operation,
                    "run_id": str(run_id) if run_id else None,
                    "command": command.model_dump(
                        mode="json",
                        exclude={"catalogs"}
                        if getattr(command, "catalogs", None) is None
                        else set(),
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            await transaction.lock_owner()
            previous = await transaction.receipt(key)
            if previous is not None:
                if previous.request_hash != digest:
                    raise JournalError("journal_idempotency_conflict")
                return previous
            if not self.enabled:
                raise JournalError("journals_disabled")
            now = utc(self.clock()) if self.clock else await transaction.now()
            current = await transaction.current()
            if current is not None:
                completed = rules.reconcile(current, now=now)
                if completed is not current:
                    await transaction.save(completed, expected_revision=current.revision)
                    current = None
            existing = (current,) if current else ()
            if operation == "activate":
                template = await transaction.template(command.template_id, command.template_version)
                if template is None:
                    raise JournalError("journal_template_not_found")
                result = rules.activate(
                    template,
                    run_id=uuid4(),
                    owner=owner,
                    timezone=command.timezone,
                    now=now,
                    existing=existing,
                )
                expected = None
            else:
                run = await transaction.run(run_id)
                if run is None:
                    raise JournalError("journal_not_found")
                expected = command.expected_revision
                arguments = dict(expected_revision=expected, now=now)
                if operation == "adjust":
                    result = rules.adjust_remaining_stages(
                        run,
                        command.remaining_stages,
                        purpose=command.purpose,
                        instructions=command.instructions,
                        catalogs=command.catalogs,
                        **arguments,
                    )
                elif operation == "intention":
                    result = rules.edit_intention(run, command.text, **arguments)
                elif operation == "resume":
                    result = rules.resume(run, existing=existing, **arguments)
                else:
                    action = {"pause": rules.pause, "advance": rules.advance, "close": rules.close}
                    result = action[operation](run, **arguments)
            await transaction.save(result, expected_revision=expected)
            receipt = MutationReceipt(
                key=key,
                owner_id=owner,
                operation=operation,
                request_hash=digest,
                run_id=result.id,
                revision=result.revision,
                recorded_at=now,
            )
            await transaction.record_receipt(receipt)
        # Context-manager exit commits before acknowledging the mutation.
        return receipt
