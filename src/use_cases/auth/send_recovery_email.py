"""Durable mail workflow: protected payload, expiry, replay safety and bounded retries."""

from datetime import timedelta

from src.core.processing.errors import WorkflowFailure
from src.core.processing.workflows import WorkflowDefinition


class SendRecoveryEmail:
    def __init__(self, repository, secrets, transport):
        self.repository, self.secrets, self.transport = repository, secrets, transport

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, frozenset(), requires_workspace=False)

    async def execute(self, context):
        retry_delay = None
        async with self.repository.transaction() as transaction:
            delivery, address = await transaction.delivery_context(context.record.resource_id)
            if delivery is None:
                return  # Expired payload cleanup can precede a very late broker replay.
            if (
                delivery.processing_id != context.record.id
                or delivery.user_id != context.record.user_id
            ):
                raise WorkflowFailure("recovery_delivery_mismatch")
            if delivery.status not in {"pending", "retrying"}:
                return
            now = await transaction.now()
            user = await transaction.user_by_id(delivery.user_id)
            if (
                address is None
                or address.challenge_id != delivery.challenge_id
                or address.consumed_at is not None
                or address.code_ciphertext is None
                or user is None
                or not user.is_active
                or user.password_login_enabled is not True
                or address.password_mac != self.secrets.password_mac(user)
            ):
                delivery.status = "cancelled"
                return
            if now >= address.expires_at:
                delivery.status = "expired"
                address.code_ciphertext = address.code_mac = None
                return
            if delivery.attempts >= 4:
                delivery.status = "failed"
                return
            await context.assert_lease()
            delivery.attempts += 1
            try:
                code = self.secrets.decrypt_code(address.code_ciphertext)
            except Exception:
                delivery.status, delivery.error_code = "failed", "recovery_payload_invalid"
                return
            result = await self.transport.send(
                user.email, code, str(delivery.id), address.expires_at
            )
            await context.assert_lease()
            finished = await transaction.now()
            delivery.error_code = result.code
            if result.accepted:
                delivery.status, delivery.provider_id = "accepted", result.provider_id
            elif result.retryable and delivery.attempts < 4 and context.record.stage_attempts < 4:
                delay = max((10, 30, 120)[delivery.attempts - 1], result.retry_after or 0)
                if finished + timedelta(seconds=delay) < address.expires_at:
                    delivery.status, retry_delay = "retrying", delay
                else:
                    delivery.status = "expired"
            else:
                delivery.status = "failed"
        if retry_delay is not None:
            raise WorkflowFailure("resend_temporary_error", retry_delay=retry_delay)
