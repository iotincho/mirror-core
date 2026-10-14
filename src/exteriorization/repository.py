"""Owner-scoped SQL operations and shared transaction boundaries."""

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.exteriorization.models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    PushSubscription,
)


class InvitationError(ValueError):
    def __init__(self, code: str, status_code: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def session_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
            raise InvitationError("invitation_not_found", 404)
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
            raise InvitationError("subscription_not_found", 404)
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
        from src.processing.models import ProcessingRecord

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

    async def deactivate_session(self, user_id: UUID, fingerprint: str) -> None:
        async with self.sessions.begin() as session:
            # Match configuration/sending lock order: preference, subscription, delivery.
            await self.preference(session, user_id)
            subscriptions = (
                await session.scalars(
                    select(PushSubscription)
                    .where(
                        PushSubscription.user_id == user_id,
                        PushSubscription.session_fingerprint == fingerprint,
                    )
                    .with_for_update()
                )
            ).all()
            for subscription in subscriptions:
                subscription.active = False
                subscription.updated_at = await self.now(session)
                await self.cancel_deliveries(session, user_id, subscription.id)
