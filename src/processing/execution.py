"""Compatibility imports; canonical implementation lives in the new layers."""

from src.core.processing.errors import LeaseLost as LeaseLost
from src.core.processing.errors import ResourceBusy as ResourceBusy
from src.core.processing.errors import WorkflowFailure as WorkflowFailure
from src.core.processing.errors import WorkflowWaiting as WorkflowWaiting
from src.core.processing.workflows import WorkflowDefinition as WorkflowDefinition
from src.core.processing.workflows import WorkflowRegistry as WorkflowRegistry
from src.use_cases.processing.context import ExecutionContext as ExecutionContext


def ExecuteProcessing(repository, registry, max_attempts=4):
    from src.bootstrap.processing import build_executor

    return build_executor(repository, registry, max_attempts)
