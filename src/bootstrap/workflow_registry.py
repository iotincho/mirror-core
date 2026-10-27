"""Build the versioned workflow registry after composition factories are importable."""

from src.bootstrap.workflows import register_workflows
from src.core.processing.workflows import WorkflowRegistry

registry = WorkflowRegistry()
register_workflows(registry)
