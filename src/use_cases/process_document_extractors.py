"""Persist the source and coordinate independently scheduled extractor children."""

from sqlalchemy.exc import SQLAlchemyError

from src.processing.execution import (
    LeaseLost,
    WorkflowDefinition,
    WorkflowFailure,
    WorkflowWaiting,
)
from src.processing.failures import failure_for


class ProcessDocumentExtractors:
    transitions = frozenset(
        {("document_persistence", "extractor_processing"), ("extractor_processing", "done")}
    )

    def __init__(self, runtime_factory):
        self.runtime_factory = runtime_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        record = context.record
        try:
            specs = record.config.get("extractors")
            if not isinstance(specs, list) or not specs:
                raise WorkflowFailure("workflow_configuration")
            names = [spec["name"] for spec in specs]
            if any(
                not isinstance(name, str) or not name or len(name) > 80 for name in names
            ) or len(names) != len(set(names)):
                raise WorkflowFailure("workflow_configuration")
            if record.stage == "document_persistence":
                async with self.runtime_factory(record.user_id) as runtime:
                    document = await runtime.document_store.get(record.resource_id)
                    await context.assert_lease()
                    await runtime.graph_store.persist_document(document)
                await context.advance("extractor_processing", document_id=str(record.resource_id))
            if record.stage == "extractor_processing":
                children = await context.repository.extractor_children(record.id, record.user_id)
                if not children or any(
                    child.status not in {"completed", "failed"} for child in children
                ):
                    await context.repository.extractors_and_wait(record, specs)
                    raise WorkflowWaiting()
                if {child.extractor_name for child in children} != set(names):
                    raise WorkflowFailure("extractor_children_mismatch")
                failed = [child for child in children if child.status == "failed"]
                if failed:
                    raise WorkflowFailure(
                        "extractors_failed", retryable=any(child.retryable for child in failed)
                    )
                await context.advance("done")
            if record.stage != "done":
                raise WorkflowFailure("invalid_workflow_stage")
        except (WorkflowFailure, WorkflowWaiting, LeaseLost, SQLAlchemyError):
            raise
        except Exception as error:
            raise failure_for(error, record.stage_attempts, "graph") from error
