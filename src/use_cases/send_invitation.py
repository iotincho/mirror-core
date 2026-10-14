"""Own delivery transitions and retry policy; Taskiq only invokes this workflow."""

from datetime import timedelta

from sqlalchemy import select

from src.exteriorization.models import (
    InvitationDelivery,
    InvitationPreference,
    PushSubscription,
)
from src.exteriorization.repository import InvitationRepository
from src.exteriorization.web_push import PushTransport
from src.processing.execution import ExecutionContext, WorkflowDefinition, WorkflowFailure


class SendInvitation:
    def __init__(self, repository: InvitationRepository, transport: PushTransport) -> None:
        self.repository, self.transport = repository, transport

    @property
    def definition(self) -> WorkflowDefinition:
        return WorkflowDefinition(self.execute, frozenset())

    async def execute(self, context: ExecutionContext) -> None:
        retry_delay = None
        error_code = None
        async with self.repository.sessions.begin() as session:
            # Use one lock order for configuration, logout and send. Holding these
            # short-lived locks through the bounded HTTP call serializes disable/logout.
            preference = await session.scalar(
                select(InvitationPreference)
                .where(
                    InvitationPreference.user_id == context.record.user_id,
                )
                .with_for_update()
            )
            delivery = await session.scalar(
                select(InvitationDelivery).where(
                    InvitationDelivery.id == context.record.resource_id,
                    InvitationDelivery.processing_id == context.record.id,
                    InvitationDelivery.user_id == context.record.user_id,
                )
            )
            if delivery is None:
                raise WorkflowFailure("invitation_delivery_missing")
            subscription = await session.scalar(
                select(PushSubscription)
                .where(
                    PushSubscription.id == delivery.subscription_id,
                    PushSubscription.user_id == context.record.user_id,
                )
                .with_for_update()
            )
            await session.refresh(delivery, with_for_update=True)
            if delivery.status not in {"pending", "retrying"}:
                return
            invitation = await self.repository.invitation(
                session,
                context.record.user_id,
                delivery.invitation_id,
            )
            now = await self.repository.now(session)
            if (
                subscription is None
                or not subscription.active
                or preference is None
                or (invitation.kind == "scheduled" and not preference.enabled)
            ):
                delivery.status, delivery.next_attempt_at = "cancelled", None
                return
            if now >= invitation.expires_at:
                delivery.status, delivery.next_attempt_at = "expired", None
                return
            if delivery.next_attempt_at is not None and delivery.next_attempt_at > now:
                raise WorkflowFailure(
                    delivery.error_code or "push_retry_pending",
                    retry_delay=(delivery.next_attempt_at - now).total_seconds(),
                )
            if delivery.attempts >= 4:
                delivery.status, delivery.next_attempt_at = "failed", None
                delivery.error_code = "push_attempts_exhausted"
                return
            await context.assert_lease()
            delivery.attempts += 1
            payload = {
                "binding_id": str(subscription.binding_id),
                "title": "Un momento para vos",
                "question": invitation.question,
                "invitation_id": str(invitation.id),
                "url": f"/?invitation_id={invitation.id}",
                "tag": f"invitation:{invitation.id}",
            }
            result = await self.transport.send(
                {
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                payload,
                max(0, int((invitation.expires_at - now).total_seconds())),
            )
            # A stale executor cannot settle an externally ambiguous send.
            await context.assert_lease()
            finished = await self.repository.now(session)
            delivery.error_code = result.code
            delivery.next_attempt_at = None
            if result.accepted:
                delivery.status, delivery.accepted_at = "accepted", finished
            elif result.expired:
                subscription.active, subscription.updated_at = False, finished
                delivery.status = "failed"
                await self.repository.cancel_deliveries(session, delivery.user_id, subscription.id)
                # The bulk cancellation must not replace this terminal result.
                delivery.status = "failed"
            elif result.retryable and delivery.attempts < 4 and context.record.stage_attempts < 4:
                delay = (10, 30, 120)[delivery.attempts - 1]
                if finished + timedelta(seconds=delay) < invitation.expires_at:
                    delivery.status = "retrying"
                    delivery.next_attempt_at = finished + timedelta(seconds=delay)
                    retry_delay, error_code = delay, result.code
                else:
                    delivery.status = "expired"
            else:
                delivery.status = "failed"
        # Commit the per-device result before handing retry scheduling to the runtime.
        if retry_delay is not None:
            raise WorkflowFailure(error_code or "push_transient_error", retry_delay=retry_delay)
