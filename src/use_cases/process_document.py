"""Persist the original document independently of any extraction layer."""

from sqlalchemy.exc import SQLAlchemyError

from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for


class ProcessDocument:
    transitions = frozenset({("document_persistence", "done")})

    def __init__(self, runtime_factory):
        self.runtime_factory = runtime_factory

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
        except (WorkflowFailure, LeaseLost, SQLAlchemyError):
            raise
        except Exception as error:
            raise failure_for(error, context.record.stage_attempts, "graph") from error
