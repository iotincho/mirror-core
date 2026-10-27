"""Own delivery transitions and retry policy; Taskiq only invokes this workflow."""

from datetime import timedelta

from src.core.exteriorization.ports import Invitations, PushTransport
from src.core.processing.errors import WorkflowFailure
from src.core.processing.ports import WorkflowContext
from src.core.processing.workflows import WorkflowDefinition


class SendInvitation:
    def __init__(self, repository: Invitations, transport: PushTransport) -> None:
        self.repository, self.transport = repository, transport

    @property
    def definition(self) -> WorkflowDefinition:
        return WorkflowDefinition(self.execute, frozenset())

    async def execute(self, context: WorkflowContext) -> None:
        retry_delay = None
        error_code = None
        async with self.repository.transaction() as transaction:
            preference, delivery, subscription = await transaction.delivery_context(
                context.record.user_id,
                context.record.id,
                context.record.resource_id,
            )
            if delivery is None:
                raise WorkflowFailure("invitation_delivery_missing")
            if delivery.status not in {"pending", "retrying"}:
                return
            invitation = await transaction.invitation(
                context.record.user_id,
                delivery.invitation_id,
            )
            now = await transaction.now()
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
            finished = await transaction.now()
            delivery.error_code = result.code
            delivery.next_attempt_at = None
            if result.accepted:
                delivery.status, delivery.accepted_at = "accepted", finished
            elif result.expired:
                subscription.active, subscription.updated_at = False, finished
                delivery.status = "failed"
                await transaction.cancel_deliveries(delivery.user_id, subscription.id)
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
