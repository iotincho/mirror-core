"""Workflow definitions and execution context independent of the storage engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.processing.errors import WorkflowFailure
from src.core.processing.models import ProcessingJob
from src.core.processing.ports import WorkflowContext


@dataclass(frozen=True)
class WorkflowDefinition:
    run: Callable[[WorkflowContext], Awaitable[None]]
    transitions: frozenset[tuple[str, str]]
    requires_workspace: bool = True


class WorkflowRegistry:
    def __init__(self):
        self.definitions: dict[tuple[str, int], WorkflowDefinition] = {}

    def register(self, name: str, version: int, definition: WorkflowDefinition):
        key = (name, version)
        if key in self.definitions:
            raise ValueError("workflow_already_registered")
        self.definitions[key] = definition

    def get(self, record: ProcessingJob) -> WorkflowDefinition:
        try:
            return self.definitions[(record.workflow, record.workflow_version)]
        except KeyError:
            raise WorkflowFailure("workflow_not_registered") from None
