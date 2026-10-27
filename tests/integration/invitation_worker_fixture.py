"""Simulated push boundary loaded only by the real Taskiq integration test."""

from src.bootstrap.invitations import get_invitation_repository
from src.bootstrap.workflow_registry import registry
from src.core.exteriorization.models import PushResult
from src.core.processing.workflows import WorkflowDefinition
from src.use_cases.exteriorization.send_invitation import SendInvitation


class AcceptPush:
    async def send(self, subscription, payload, ttl):
        return PushResult(accepted=True)


async def send(context):
    await SendInvitation(get_invitation_repository(), AcceptPush()).execute(context)


# The production workflow remains unchanged; only this process substitutes transport.
registry.definitions[("invitation_push", 1)] = WorkflowDefinition(send, frozenset())
