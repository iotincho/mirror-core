"""Detached receipt boundary over the existing atomic PostgreSQL reservation protocol."""

from src.adapters.storage.postgres.state import database_errors, receipt_snapshot, snapshot
from src.adapters.storage.postgres.submissions import SubmissionRepository
from src.adapters.storage.postgres.transactions import PostgresProcessingRequests


class PostgresSubmissions:
    def __init__(self, repository, *, config_factory, invitation_validator, submissions=None):
        self._submissions = submissions or SubmissionRepository(repository)
        self._invitation_validator = invitation_validator
        self._config_factory = config_factory
        self.processing = PostgresProcessingRequests(repository, config_factory=config_factory)

    async def get(self, owner, operation, key):
        async with database_errors():
            return receipt_snapshot(await self._submissions.get(owner, operation, key))

    async def reserve(self, **request):
        async with database_errors():
            return receipt_snapshot(
                await self._submissions.reserve(
                    **request,
                    config_factory=self._config_factory,
                )
            )

    async def accept(self, receipt):
        async with database_errors():
            return snapshot(await self._submissions.accept(receipt))

    async def release(self, receipt):
        async with database_errors():
            await self._submissions.release(receipt)

    async def claim_pending(self):
        async with database_errors():
            return [receipt_snapshot(row) for row in await self._submissions.claim_pending()]

    async def validate_invitation(self, owner, invitation_id):
        async with database_errors(), self._submissions.sessions() as session:
            await self._invitation_validator(session, owner, invitation_id)
