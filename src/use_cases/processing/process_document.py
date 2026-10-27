"""Persist the original document independently of any extraction layer."""

from src.core.processing.errors import LeaseLost, StorageUnavailable, WorkflowFailure
from src.core.processing.ports import WorkspaceFactory
from src.core.processing.workflows import WorkflowDefinition


class ProcessDocument:
    transitions = frozenset({("document_persistence", "done")})

    def __init__(self, runtime_factory: WorkspaceFactory, *, failure_for):
        self.runtime_factory = runtime_factory
        self.failure_for = failure_for

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        if context.record.workflow_version != 2:
            raise WorkflowFailure("extraction_retired")
        try:
            async with self.runtime_factory(context.record.user_id) as runtime:
                document = await runtime.document_store.get(context.record.resource_id)
                await context.assert_lease()
                await runtime.graph_store.persist_document(document)
                await context.advance("done", document_id=str(document.id))
        except (WorkflowFailure, LeaseLost, StorageUnavailable):
            raise
        except Exception as error:
            raise self.failure_for(error, context.record.stage_attempts, "graph") from error
