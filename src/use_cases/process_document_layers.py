"""Document workflow with separately recoverable extraction and layer writes."""

from uuid import uuid5

from sqlalchemy.exc import SQLAlchemyError

from src.extractors.artifacts import LayerArtifacts
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for


class ProcessDocumentLayers:
    transitions = frozenset(
        {
            ("document_persistence", "layer_extraction"),
            ("layer_extraction", "layer_persistence"),
            ("layer_persistence", "done"),
        }
    )

    def __init__(self, runtime_factory, extractor_factory):
        self.runtime_factory, self.extractor_factory = runtime_factory, extractor_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        record = context.record
        if record.workflow_version != 3:
            raise WorkflowFailure("workflow_configuration")
        service = "graph"
        try:
            specifications = record.config.get("extractors")
            if not isinstance(specifications, list) or not specifications:
                raise WorkflowFailure("workflow_configuration")
            names = [spec["name"] for spec in specifications]
            if len(names) != len(set(names)):
                raise WorkflowFailure("workflow_configuration")
            async with self.runtime_factory(record.user_id) as runtime:
                document = await runtime.document_store.get(record.resource_id)
                artifacts = LayerArtifacts(runtime.context.filesystem_root / "layers")
                if record.stage == "document_persistence":
                    await context.assert_lease()
                    await runtime.graph_store.persist_document(document)
                    await context.advance("layer_extraction", document_id=str(document.id))
                if record.stage == "layer_extraction":
                    service = "extraction"
                    for spec in specifications:
                        await context.assert_lease()
                        extractor = self.extractor_factory(runtime, spec, extracting=True)
                        await extractor.extract(document, run_id=uuid5(record.id, spec["name"]))
                    await context.assert_lease()
                    await context.advance("layer_persistence")
                if record.stage == "layer_persistence":
                    service = "graph"
                    for spec in specifications:
                        output = await artifacts.get(document.id, uuid5(record.id, spec["name"]))
                        if output is None:
                            raise WorkflowFailure("layer_artifact_missing")
                        await context.assert_lease()
                        extractor = self.extractor_factory(runtime, spec, extracting=False)
                        await extractor.persist(output)
                    await context.assert_lease()
                    await context.advance("done")
                if record.stage != "done":
                    raise WorkflowFailure("invalid_workflow_stage")
        except (WorkflowFailure, LeaseLost, SQLAlchemyError):
            raise
        except Exception as error:
            raise failure_for(error, record.stage_attempts, service) from error
