"""Authenticated configuration and manual tests share the generation use case."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.exteriorization.models import Invitation, InvitationPreference, PushSubscription
from src.exteriorization.repository import InvitationError, InvitationRepository
from src.exteriorization.scheduling import next_occurrence
from src.notifications.invitations import add_invitation_notification
from src.notifications.models import Notification
from src.use_cases.generate_invitation import GenerateInvitation
from src.workspaces.models import UserWorkspace


class ConfigureInvitations:
    def __init__(self, repository: InvitationRepository) -> None:
        self.repository = repository

    async def preferences(self, user_id: UUID) -> InvitationPreference:
        async with self.repository.sessions.begin() as session:
            return await self.repository.preference(session, user_id)

    async def configure(
        self,
        user_id: UUID,
        enabled: bool,
        local_time: str,
        timezone: str,
    ) -> InvitationPreference:
        async with self.repository.sessions.begin() as session:
            preference = await self.repository.preference(session, user_id)
            now = await self.repository.now(session)
            changed = (preference.enabled, preference.local_time, preference.timezone) != (
                enabled,
                local_time,
                timezone,
            )
            preference.enabled, preference.local_time, preference.timezone = (
                enabled,
                local_time,
                timezone,
            )
            if not enabled:
                preference.next_due_at = None
                await self.repository.cancel_deliveries(session, user_id)
            elif changed or preference.next_due_at is None:
                preference.next_due_at = next_occurrence(now, local_time, timezone)
            preference.updated_at = now
            return preference

    async def subscribe(
        self,
        user_id: UUID,
        fingerprint: str,
        endpoint: str,
        p256dh: str,
        auth: str,
    ) -> PushSubscription:
        async with self.repository.sessions.begin() as session:
            await self.repository.preference(session, user_id)
            await session.execute(
                insert(PushSubscription)
                .values(
                    id=uuid4(),
                    user_id=user_id,
                    session_fingerprint=fingerprint,
                    endpoint=endpoint,
                    p256dh=p256dh,
                    auth=auth,
                )
                .on_conflict_do_nothing(index_elements=["endpoint"])
            )
            subscription = await session.scalar(
                select(PushSubscription)
                .where(
                    PushSubscription.endpoint == endpoint,
                )
                .with_for_update()
            )
            # A new browser subscription must reconcile a previous account locally first.
            # Do not rewrite historical ownership referenced by delivery records.
            if subscription.user_id != user_id:
                raise InvitationError("subscription_account_conflict", 409)
            if subscription.session_fingerprint != fingerprint:
                subscription.binding_id = uuid4()
                await self.repository.cancel_deliveries(session, user_id, subscription.id)
            subscription.session_fingerprint = fingerprint
            subscription.p256dh, subscription.auth = p256dh, auth
            subscription.active = True
            subscription.updated_at = await self.repository.now(session)
            return subscription

    async def unsubscribe(self, user_id: UUID, fingerprint: str, subscription_id: UUID) -> None:
        async with self.repository.sessions.begin() as session:
            await self.repository.preference(session, user_id)
            subscription = await self.repository.subscription(
                session,
                user_id,
                subscription_id,
                fingerprint,
            )
            subscription.active = False
            subscription.updated_at = await self.repository.now(session)
            await self.repository.cancel_deliveries(session, user_id, subscription.id)

    async def test(
        self,
        user_id: UUID,
        fingerprint: str,
        subscription_id: UUID,
        key: UUID,
    ) -> Invitation:
        async with self.repository.sessions.begin() as session:
            preference = await self.repository.preference(session, user_id)
            subscription = await self.repository.subscription(
                session,
                user_id,
                subscription_id,
                fingerprint,
            )
            previous = await session.scalar(
                select(Invitation).where(
                    Invitation.user_id == user_id,
                    Invitation.request_key == key,
                )
            )
            if previous is not None:
                if previous.test_subscription_id != subscription_id:
                    raise InvitationError("idempotency_conflict", 409)
                await add_invitation_notification(session, previous)
                return previous
            if not subscription.active:
                raise InvitationError("active_subscription_required", 409)
            active = await session.scalar(
                select(UserWorkspace.user_id).where(
                    UserWorkspace.user_id == user_id,
                    UserWorkspace.status == "active",
                )
            )
            if active is None:
                raise InvitationError("workspace_unavailable", 409)
            now = await self.repository.now(session)
            if preference.last_test_at and now < preference.last_test_at + timedelta(minutes=1):
                raise InvitationError("test_rate_limited", 429)
            preference.last_test_at = now
            return await GenerateInvitation().execute(
                session,
                preference,
                now,
                now,
                [subscription],
                request_key=key,
            )

    async def get_invitation(self, user_id: UUID, invitation_id: UUID) -> Invitation:
        async with self.repository.sessions() as session:
            return await self.repository.invitation(session, user_id, invitation_id)

    async def open_invitation(self, user_id: UUID, invitation_id: UUID) -> Invitation:
        async with self.repository.sessions.begin() as session:
            invitation = await session.scalar(
                select(Invitation)
                .where(
                    Invitation.id == invitation_id,
                    Invitation.user_id == user_id,
                )
                .with_for_update()
            )
            if invitation is None:
                raise InvitationError("invitation_not_found", 404)
            if invitation.first_opened_at is None:
                invitation.first_opened_at = await self.repository.now(session)
            await session.execute(
                update(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.deduplication_key == f"invitation:{invitation_id}",
                )
                .values(read_at=func.coalesce(Notification.read_at, invitation.first_opened_at))
            )
            return invitation
