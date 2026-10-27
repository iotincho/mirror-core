"""Use actual Taskiq execution with a controlled clock and simulated push provider."""

from invitation_test_support import CapturedPush, invitation_repository

from src.bootstrap.workflow_registry import registry
from src.core.processing.workflows import WorkflowDefinition
from src.use_cases.exteriorization.send_invitation import SendInvitation
from src.use_cases.processing.context import ExecutionContext


async def send(context: ExecutionContext) -> None:
    await SendInvitation(invitation_repository(), CapturedPush()).execute(context)


registry.definitions[("invitation_push", 1)] = WorkflowDefinition(send, frozenset())
