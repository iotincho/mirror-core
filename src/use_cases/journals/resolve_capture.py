"""Resolve historical capture provenance without a mutable current-stage lookup."""

from src.core.journals.contracts import validate_entry_reference
from src.core.journals.ports import Journals
from src.use_cases.journals.manage import require_access


class ResolveJournalCapture:
    def __init__(self, repository: Journals):
        self.repository = repository

    async def resolve(self, owner, supplied, *, invitation_id=None):
        async with self.repository.transaction(owner) as transaction:
            await require_access(transaction)
            response = (
                await transaction.response_context(invitation_id)
                if invitation_id is not None
                else None
            )
            reference = response.reference if response is not None else supplied
            archived = (
                await transaction.run(reference.run_id, reference.run_revision)
                if reference is not None
                else None
            )
            return validate_entry_reference(owner, supplied, archived, response=response)
