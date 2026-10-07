"""One durable job owns extraction and persistence of one layer."""

from sqlalchemy.exc import SQLAlchemyError

from src.extractors.artifacts import LayerArtifacts
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for


class ProcessExtractor:
    transitions = frozenset({("extraction", "persistence"), ("persistence", "done")})

    def __init__(self, runtime_factory, extractor_factory):
        self.runtime_factory, self.extractor_factory = runtime_factory, extractor_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        record = context.record
        service = "extraction" if record.stage == "extraction" else "graph"
        try:
            spec = record.config["extractor"]
            if spec["name"] != record.extractor_name or record.extraction_run_id is None:
                raise WorkflowFailure("extractor_configuration")
            async with self.runtime_factory(record.user_id) as runtime:
                document = await runtime.document_store.get(record.resource_id)
                if record.stage == "extraction":
                    await context.assert_lease()
                    extractor = self.extractor_factory(runtime, spec, extracting=True)
                    await extractor.extract(document, run_id=record.extraction_run_id)
                    await context.assert_lease()
                    await context.advance("persistence")
                if record.stage == "persistence":
                    service = "graph"
                    artifacts = LayerArtifacts(runtime.context.filesystem_root / "layers")
                    output = await artifacts.get(document.id, record.extraction_run_id)
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
