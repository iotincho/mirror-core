"""Validate workflow transitions before committing checkpoints through the state port."""

from dataclasses import dataclass

from src.core.processing.errors import WorkflowFailure
from src.core.processing.models import ProcessingJob
from src.core.processing.ports import ExecutionStore
from src.core.processing.workflows import WorkflowDefinition


@dataclass
class ExecutionContext:
    repository: ExecutionStore
    record: ProcessingJob
    definition: WorkflowDefinition

    async def advance(self, stage: str, **checkpoints):
        if (self.record.stage, stage) not in self.definition.transitions:
            raise WorkflowFailure("invalid_workflow_transition")
        await self.repository.advance(self.record, stage, checkpoints)

    async def assert_lease(self):
        await self.repository.assert_lease(self.record)
