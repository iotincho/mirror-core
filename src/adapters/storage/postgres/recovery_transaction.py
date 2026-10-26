"""Atomic recovery budgets, challenge/password updates, revocation and mail outbox."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import noload

from src.adapters.storage.postgres.accounts import AccessToken, User
from src.adapters.storage.postgres.invitation_models import InvitationDelivery, PushSubscription
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.recovery_models import RecoveryAddress, RecoveryDelivery
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.snapshots import SnapshotTracker
from src.core.auth.identity import AccountCredentials
from src.core.auth.recovery import RecoveryAddress as Address
from src.core.auth.recovery import RecoveryDelivery as Delivery
from src.core.auth.recovery import RecoveryIP as IP


class RecoveryTransaction(SnapshotTracker):
    def __init__(self, repository, session):
        super().__init__()
        self.repository, self.session = repository, session

    async def now(self):
        return await self.repository.now(self.session)

    async def ip(self, key):
        return self.track(await self.repository.ip(self.session, key), IP)

    async def address(self, key):
        return self.track(await self.repository.address(self.session, key), Address)

    async def user(self, email, *, lock=False):
        statement = (
            select(User)
            .options(noload(User.oauth_accounts))
            .where(func.lower(User.email) == email.strip().lower())
        )
        if lock:
            statement = statement.with_for_update(of=User, key_share=True)
        return self.track(await self.session.scalar(statement), AccountCredentials)

    async def user_by_id(self, user_id):
        return self.track(
            await self.session.scalar(select(User).where(User.id == user_id)), AccountCredentials
        )

    async def delivery_context(self, delivery_id):
        delivery = await self.session.get(RecoveryDelivery, delivery_id)
        if delivery is None:
            return None, None
        # Preserve the reset/sender lock order: address first, delivery second.
        address = await self.session.get(
            RecoveryAddress, delivery.address_key, with_for_update=True
        )
        await self.session.refresh(delivery, with_for_update=True)
        return self.track(delivery, Delivery), self.track(address, Address)

    async def enqueue_email(
        self, delivery_id, processing_id, user_id, address_key, challenge_id, now
    ):
        self.synchronize()
        record = ProcessingRecord(
            id=processing_id,
            user_id=user_id,
            workflow="password_recovery_email",
            workflow_version=1,
            resource_kind="auth_email",
            resource_id=delivery_id,
            stage="send",
            config={},
            available_at=now,
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            RecoveryDelivery(
                id=delivery_id,
                user_id=user_id,
                address_key=address_key,
                challenge_id=challenge_id,
                processing_id=record.id,
            )
        )
        ProcessingRepository.schedule(self.session, record)

    async def revoke_access(self, user_id, now):
        self.synchronize()
        await self.session.execute(delete(AccessToken).where(AccessToken.user_id == user_id))
        # Keep the push sender/logout preference lock order. All changes commit
        # with password/session version/challenge consumption, including pending sends.
        await InvitationRepository(self.repository.sessions).preference(self.session, user_id)
        await self.session.execute(
            update(PushSubscription)
            .where(PushSubscription.user_id == user_id)
            .values(active=False, updated_at=now)
        )
        await self.session.execute(
            update(InvitationDelivery)
            .where(
                InvitationDelivery.user_id == user_id,
                InvitationDelivery.status.in_(["pending", "retrying"]),
            )
            .values(status="cancelled", next_attempt_at=None)
        )
