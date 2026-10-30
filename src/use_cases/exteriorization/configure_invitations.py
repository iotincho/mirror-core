"""Owner-scoped consent, device binding and explicit tests through atomic ports."""

from datetime import timedelta
from uuid import UUID, uuid4

from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.ports import Invitations, PushRegistration
from src.core.exteriorization.scheduling import next_occurrence
from src.use_cases.exteriorization.generate_invitation import GenerateInvitation
from src.use_cases.exteriorization.record_activity import RecordInvitationActivity


class ConfigureInvitations:
    def __init__(
        self, repository: Invitations, *, push: PushRegistration | None = None, policy=None
    ):
        self.repository, self.push = repository, push
        self.policy = policy
        self.activity = RecordInvitationActivity(repository)

    def public_key(self):
        if self.push is None:
            raise InvitationError("web_push_not_configured")
        return self.push.public_key()

    def validate_push_subscription(self, endpoint, p256dh, auth):
        self.public_key()
        self.push.validate(endpoint, p256dh, auth)

    async def preferences(self, user_id: UUID):
        async with self.repository.transaction() as transaction:
            return await transaction.preference(user_id)

    async def configure(self, user_id: UUID, enabled: bool, local_time: str, timezone: str):
        async with self.repository.transaction() as transaction:
            preference = await transaction.preference(user_id)
            now = await transaction.now()
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
                await transaction.cancel_deliveries(user_id)
            elif changed or preference.next_due_at is None:
                preference.next_due_at = next_occurrence(now, local_time, timezone)
            preference.updated_at = now
            return preference

    async def subscribe(self, user_id, fingerprint, endpoint, p256dh, auth):
        async with self.repository.transaction() as transaction:
            await transaction.preference(user_id)
            subscription = await transaction.upsert_subscription(
                user_id,
                fingerprint,
                endpoint,
                p256dh,
                auth,
            )
            if subscription.user_id != user_id:
                raise InvitationError("subscription_account_conflict")
            if subscription.session_fingerprint != fingerprint:
                subscription.binding_id = uuid4()
                await transaction.cancel_deliveries(user_id, subscription.id)
            subscription.session_fingerprint = fingerprint
            subscription.p256dh, subscription.auth = p256dh, auth
            subscription.active = True
            subscription.updated_at = await transaction.now()
            return subscription

    async def unsubscribe(self, user_id, fingerprint, subscription_id):
        async with self.repository.transaction() as transaction:
            await transaction.preference(user_id)
            subscription = await transaction.subscription(user_id, subscription_id, fingerprint)
            subscription.active = False
            subscription.updated_at = await transaction.now()
            await transaction.cancel_deliveries(user_id, subscription.id)

    async def deactivate_session(self, user_id, fingerprint):
        async with self.repository.transaction() as transaction:
            await transaction.preference(user_id)
            for subscription in await transaction.session_subscriptions(user_id, fingerprint):
                subscription.active = False
                subscription.updated_at = await transaction.now()
                await transaction.cancel_deliveries(user_id, subscription.id)

    async def test(self, user_id, fingerprint, subscription_id, key):
        async with self.repository.transaction() as transaction:
            preference = await transaction.preference(user_id)
            subscription = await transaction.subscription(user_id, subscription_id, fingerprint)
            previous = await transaction.find_test(user_id, key)
            if previous is not None:
                if previous.test_subscription_id != subscription_id:
                    raise InvitationError("idempotency_conflict")
                await transaction.notify(previous)
                return previous
            if not subscription.active:
                raise InvitationError("active_subscription_required")
            if not await transaction.workspace_active(user_id):
                raise InvitationError("workspace_unavailable")
            now = await transaction.now()
            if preference.last_test_at and now < preference.last_test_at + timedelta(minutes=1):
                raise InvitationError("test_rate_limited")
            preference.last_test_at = now
            invitation = await GenerateInvitation(policy=self.policy).execute(
                transaction,
                preference,
                now,
                now,
                [subscription],
                request_key=key,
            )
            if invitation is None:
                raise InvitationError("no_eligible_questions")
            return invitation

    async def get_invitation(self, user_id, invitation_id):
        async with self.repository.transaction() as transaction:
            invitation = await transaction.invitation(user_id, invitation_id)
            return await self._available_questions(transaction, user_id, invitation)

    async def open_invitation(self, user_id, invitation_id):
        async with self.repository.transaction() as transaction:
            invitation = await transaction.invitation(user_id, invitation_id, lock=True)
            if invitation.first_opened_at is None:
                invitation.first_opened_at = await transaction.now()
            await transaction.mark_invitation_read(
                user_id, invitation_id, invitation.first_opened_at
            )
            return await self._available_questions(transaction, user_id, invitation)

    @staticmethod
    async def _available_questions(transaction, user_id, invitation):
        now = await transaction.now()
        states = await transaction.question_topic_states(user_id, invitation.id)
        excluded = {
            identifier
            for identifier, topic in states
            if topic.status in {"closed", "do_not_prompt"}
            or (topic.status == "paused" and now < topic.paused_until)
        }
        invitation._available_question_ids = tuple(
            q.id
            for group in invitation.question_groups
            for q in group.questions
            if q.id not in excluded
        )
        return invitation
