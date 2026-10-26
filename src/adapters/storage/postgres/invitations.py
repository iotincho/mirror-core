"""Owner-scoped SQL operations and shared transaction boundaries."""

from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    PushSubscription,
)
from src.adapters.storage.postgres.state import database_errors
from src.core.exteriorization.models import InvitationError as InvitationError
from src.core.exteriorization.models import session_fingerprint as session_fingerprint


class InvitationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def preference(self, session: AsyncSession, user_id: UUID) -> InvitationPreference:
        await session.execute(
            insert(InvitationPreference).values(user_id=user_id).on_conflict_do_nothing()
        )
        return await session.scalar(
            select(InvitationPreference)
            .where(InvitationPreference.user_id == user_id)
            .with_for_update()
        )

    async def now(self, session: AsyncSession) -> datetime:
        return await session.scalar(select(func.clock_timestamp()))

    async def invitation(
        self, session: AsyncSession, user_id: UUID, invitation_id: UUID
    ) -> Invitation:
        invitation = await session.scalar(
            select(Invitation).where(Invitation.id == invitation_id, Invitation.user_id == user_id)
        )
        if invitation is None:
            raise InvitationError("invitation_not_found")
        return invitation

    async def subscription(
        self,
        session: AsyncSession,
        user_id: UUID,
        subscription_id: UUID,
        fingerprint: str | None = None,
    ) -> PushSubscription:
        query = select(PushSubscription).where(
            PushSubscription.id == subscription_id,
            PushSubscription.user_id == user_id,
        )
        if fingerprint is not None:
            query = query.where(PushSubscription.session_fingerprint == fingerprint)
        subscription = await session.scalar(query.with_for_update())
        if subscription is None:
            raise InvitationError("subscription_not_found")
        return subscription

    async def cancel_deliveries(
        self,
        session: AsyncSession,
        user_id: UUID,
        subscription_id: UUID | None = None,
    ) -> None:
        query = update(InvitationDelivery).where(
            InvitationDelivery.user_id == user_id,
            InvitationDelivery.status.in_(["pending", "retrying"]),
        )
        if subscription_id is not None:
            query = query.where(InvitationDelivery.subscription_id == subscription_id)
        await session.execute(query.values(status="cancelled", next_attempt_at=None))

    async def reconcile_deliveries(self, session: AsyncSession, now: datetime) -> None:
        from src.adapters.storage.postgres.models import ProcessingRecord

        # Recovery may exhaust a job's lease attempts without running its use case.
        await session.execute(
            update(InvitationDelivery)
            .where(
                InvitationDelivery.status.in_(["pending", "retrying"]),
                InvitationDelivery.processing_id.in_(
                    select(ProcessingRecord.id).where(
                        ProcessingRecord.workflow == "invitation_push",
                        ProcessingRecord.status == "failed",
                    )
                ),
            )
            .values(status="failed", next_attempt_at=None, error_code="push_job_failed")
        )
        await session.execute(
            update(InvitationDelivery)
            .where(
                InvitationDelivery.status.in_(["pending", "retrying"]),
                InvitationDelivery.invitation_id.in_(
                    select(Invitation.id).where(
                        Invitation.expires_at <= now,
                    )
                ),
            )
            .values(status="expired", next_attempt_at=None)
        )

    @asynccontextmanager
    async def transaction(self):
        from src.adapters.storage.postgres.invitation_transaction import InvitationTransaction

        async with database_errors(), self.sessions.begin() as session:
            transaction = InvitationTransaction(self, session)
            yield transaction
            transaction.synchronize()
