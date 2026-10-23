"""One durable job owns extraction and persistence of one layer."""

from src.core.processing.errors import LeaseLost, StorageUnavailable, WorkflowFailure
from src.core.processing.ports import WorkspaceFactory
from src.core.processing.workflows import WorkflowDefinition


class ProcessExtractor:
    transitions = frozenset({("extraction", "persistence"), ("persistence", "done")})

    def __init__(
        self,
        runtime_factory: WorkspaceFactory,
        extractor_factory,
        *,
        artifacts_factory,
        prepare_persistence,
        failure_for,
    ):
        self.runtime_factory, self.extractor_factory = runtime_factory, extractor_factory
        self.artifacts_factory = artifacts_factory
        self.prepare_persistence = prepare_persistence
        self.failure_for = failure_for

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
            if spec.get("key", spec["name"]) != record.extractor_key:
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
                    artifacts = self.artifacts_factory(runtime)
                    output = await artifacts.get(document.id, record.extraction_run_id)
                    if output is None:
                        raise WorkflowFailure("layer_artifact_missing")
                    await context.assert_lease()
                    extractor = self.extractor_factory(runtime, spec, extracting=False)
                    await self.prepare_persistence(extractor, context)
                    await extractor.persist(output)
                    await context.assert_lease()
                    await context.advance("done")
                if record.stage != "done":
                    raise WorkflowFailure("invalid_workflow_stage")
        except (WorkflowFailure, LeaseLost, StorageUnavailable):
            raise
        except Exception as error:
            decision = self.failure_for(error, record, service)
            if decision.suppress_cause:
                raise decision.failure from None
            raise decision.failure from error
