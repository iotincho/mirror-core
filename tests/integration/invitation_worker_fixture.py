"""Simulated push boundary loaded only by the real Taskiq integration test."""

from src.exteriorization.dependencies import get_invitation_repository
from src.exteriorization.web_push import PushResult
from src.processing.execution import WorkflowDefinition
from src.processing.runtime import registry
from src.use_cases.send_invitation import SendInvitation


class AcceptPush:
    async def send(self, subscription, payload, ttl):
        return PushResult(accepted=True)


async def send(context):
    await SendInvitation(get_invitation_repository(), AcceptPush()).execute(context)


# The production workflow remains unchanged; only this process substitutes transport.
registry.definitions[("invitation_push", 1)] = WorkflowDefinition(send, frozenset())
