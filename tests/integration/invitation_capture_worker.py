"""Use actual Taskiq execution with a controlled clock and simulated push provider."""

from invitation_test_support import CapturedPush, invitation_repository

from src.processing.execution import ExecutionContext, WorkflowDefinition
from src.processing.runtime import registry
from src.use_cases.exteriorization.send_invitation import SendInvitation


async def send(context: ExecutionContext) -> None:
    await SendInvitation(invitation_repository(), CapturedPush()).execute(context)


registry.definitions[("invitation_push", 1)] = WorkflowDefinition(send, frozenset())
