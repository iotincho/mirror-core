"""Invitation state and inbox/job writes under the same PostgreSQL transaction."""

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    PushSubscription,
)
from src.adapters.storage.postgres.invitation_notifications import add_invitation_notification
from src.adapters.storage.postgres.invitation_question_models import InvitationOccurrence
from src.adapters.storage.postgres.invitation_questions import QuestionTransaction
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.notification_models import Notification
from src.adapters.storage.postgres.prepared_question_transaction import PreparedQuestionTransaction
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.snapshots import SnapshotTracker
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.exteriorization.contracts import Trigger
from src.core.exteriorization.models import Invitation as InvitationState
from src.core.exteriorization.models import InvitationDelivery as DeliveryState
from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.models import InvitationPreference as PreferenceState
from src.core.exteriorization.models import PushSubscription as SubscriptionState


class InvitationTransaction(SnapshotTracker, QuestionTransaction, PreparedQuestionTransaction):
    def __init__(self, repository, session):
        super().__init__()
        self.repository, self.session = repository, session

    async def now(self):
        return await self.repository.now(self.session)

    async def preference(self, owner):
        return self.track(await self.repository.preference(self.session, owner), PreferenceState)

    async def cancel_deliveries(self, owner, subscription_id=None):
        self.synchronize()
        await self.repository.cancel_deliveries(self.session, owner, subscription_id)

    async def subscription(self, owner, identifier, fingerprint=None):
        return self.track(
            await self.repository.subscription(self.session, owner, identifier, fingerprint),
            SubscriptionState,
        )

    async def upsert_subscription(self, owner, fingerprint, endpoint, p256dh, auth):
        await self.session.execute(
            insert(PushSubscription)
            .values(
                id=uuid4(),
                user_id=owner,
                session_fingerprint=fingerprint,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
            )
            .on_conflict_do_nothing(index_elements=["endpoint"])
        )
        row = await self.session.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint).with_for_update()
        )
        return self.track(row, SubscriptionState)

    async def session_subscriptions(self, owner, fingerprint):
        rows = await self.session.scalars(
            select(PushSubscription)
            .where(
                PushSubscription.user_id == owner,
                PushSubscription.session_fingerprint == fingerprint,
            )
            .with_for_update()
        )
        return [self.track(row, SubscriptionState) for row in rows]

    async def find_test(self, owner, key):
        row = await self.session.scalar(
            select(Invitation).where(
                Invitation.user_id == owner,
                Invitation.request_key == key,
            )
        )
        return self.track(row, InvitationState)

    async def workspace_active(self, owner):
        return (
            await self.session.scalar(
                select(UserWorkspace.user_id).where(
                    UserWorkspace.user_id == owner,
                    UserWorkspace.status == "active",
                )
            )
            is not None
        )

    async def invitation(self, owner, identifier, *, lock=False):
        if not lock:
            row = await self.repository.invitation(self.session, owner, identifier)
        else:
            row = await self.session.scalar(
                select(Invitation)
                .where(
                    Invitation.id == identifier,
                    Invitation.user_id == owner,
                )
                .with_for_update()
            )
            if row is None:
                raise InvitationError("invitation_not_found")
        return self.track(row, InvitationState)

    async def mark_invitation_read(self, owner, identifier, when):
        self.synchronize()
        await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == owner,
                Notification.deduplication_key == f"invitation:{identifier}",
            )
            .values(read_at=func.coalesce(Notification.read_at, when))
        )

    async def history(self, owner):
        rows = await self.session.scalars(
            select(Invitation)
            .where(Invitation.user_id == owner, Invitation.kind == "scheduled")
            .order_by(Invitation.created_at.desc(), Invitation.id.desc())
            .limit(7)
        )
        return tuple(
            Trigger(**{field: getattr(row, field) for field in Trigger.model_fields})
            for row in rows
        )

    async def add_invitation(self, invitation, *, topic_bindings=()):
        self.synchronize()
        self.session.add(Invitation(**asdict(invitation)))
        await self.session.flush()
        await self.add_question_indexes(invitation, topic_bindings)
        if invitation.kind == "scheduled":
            self.session.add(
                InvitationOccurrence(
                    user_id=invitation.user_id,
                    local_date=invitation.local_date,
                    outcome="published",
                    recorded_at=invitation.created_at,
                )
            )

    async def notify(self, invitation):
        await add_invitation_notification(self.session, invitation)

    async def enqueue_push(
        self, delivery_id, processing_id, owner, invitation_id, subscription_id, now
    ):
        record = ProcessingRecord(
            id=processing_id,
            user_id=owner,
            workflow="invitation_push",
            workflow_version=1,
            stage="push_send",
            resource_kind="invitation_delivery",
            resource_id=delivery_id,
            config={},
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            InvitationDelivery(
                id=delivery_id,
                user_id=owner,
                invitation_id=invitation_id,
                subscription_id=subscription_id,
                processing_id=record.id,
                status="pending",
                next_attempt_at=now,
            )
        )
        ProcessingRepository.schedule(self.session, record)

    async def reconcile_deliveries(self, now):
        await self.repository.reconcile_deliveries(self.session, now)

    async def due_preferences(self, now):
        rows = await self.session.scalars(
            select(InvitationPreference)
            .where(
                InvitationPreference.enabled.is_(True),
                InvitationPreference.next_due_at <= now,
            )
            .order_by(InvitationPreference.next_due_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        return [self.track(row, PreferenceState) for row in rows]

    async def active_subscriptions(self, owner):
        rows = await self.session.scalars(
            select(PushSubscription)
            .where(
                PushSubscription.user_id == owner,
                PushSubscription.active.is_(True),
            )
            .order_by(PushSubscription.id)
            .with_for_update()
        )
        return [self.track(row, SubscriptionState) for row in rows]

    async def scheduled_exists(self, owner, day):
        if await self.session.get(InvitationOccurrence, (owner, day)) is not None:
            return True
        return (
            await self.session.scalar(
                select(Invitation.id).where(
                    Invitation.user_id == owner,
                    Invitation.kind == "scheduled",
                    Invitation.local_date == day,
                )
            )
            is not None
        )

    async def delivery_context(self, owner, job_id, delivery_id):
        preference = await self.session.scalar(
            select(InvitationPreference)
            .where(
                InvitationPreference.user_id == owner,
            )
            .with_for_update()
        )
        delivery = await self.session.scalar(
            select(InvitationDelivery).where(
                InvitationDelivery.id == delivery_id,
                InvitationDelivery.processing_id == job_id,
                InvitationDelivery.user_id == owner,
            )
        )
        if delivery is None:
            return self.track(preference, PreferenceState), None, None
        subscription = await self.session.scalar(
            select(PushSubscription)
            .where(
                PushSubscription.id == delivery.subscription_id,
                PushSubscription.user_id == owner,
            )
            .with_for_update()
        )
        await self.session.refresh(delivery, with_for_update=True)
        return (
            self.track(preference, PreferenceState),
            self.track(delivery, DeliveryState),
            self.track(subscription, SubscriptionState),
        )
