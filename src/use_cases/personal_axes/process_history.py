"""One historical note reuses the extractor lifecycle and durable checkpoints."""

from uuid import UUID

from src.core.documents.ports import DocumentNotFoundError
from src.core.extractors.contracts import content_hash
from src.core.extractors.personal_axes.history import current_extraction
from src.core.extractors.personal_axes.models import AxisError, AxisSpecification
from src.core.processing.errors import LeaseLost, StorageUnavailable, WorkflowFailure
from src.core.processing.workflows import WorkflowDefinition
from src.use_cases.personal_axes.persist import PersistPersonalAxis

TRANSIENT_AXIS_ERRORS = {
    "axis_graph_unavailable",
    "axis_graph_incomplete",
    "axis_evidence_invalid",
    "axis_specification_mismatch",
    "axis_storage_unavailable",
    "axis_provider_configuration",
}


class ProcessAxisHistory:
    transitions = frozenset(
        {("extraction", "persistence"), ("extraction", "done"), ("persistence", "done")}
    )

    def __init__(
        self,
        runtime_factory,
        extractor_factory,
        *,
        history_factory,
        artifacts_factory,
        execution,
        write_contexts,
        failure_for,
    ):
        self.runtime_factory, self.extractor_factory = runtime_factory, extractor_factory
        self.history_factory, self.artifacts_factory = history_factory, artifacts_factory
        self.execution, self.persistence = execution, PersistPersonalAxis(write_contexts)
        self.failure_for = failure_for

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def outcome(self, context, value):
        await self.execution.outcome(context.record, value)
        if context.record.stage != "done":
            await context.advance("done")

    async def execute(self, context):
        record = context.record
        try:
            started = await self.execution.begin(record)
            if started.skip:
                await self.outcome(context, started.outcome or "stopped")
                return
            async with self.runtime_factory(record.user_id) as runtime:
                document = await runtime.document_store.get(record.resource_id)
                if content_hash(document.content) != record.config["source_hash"]:
                    await self.outcome(context, "changed")
                    return
                spec = record.config["extractor"]
                if record.stage == "extraction":
                    history = self.history_factory(runtime)
                    previous = (await history.coverage(UUID(spec["axis_id"]), document.id)).get(
                        str(document.id)
                    )
                    if current_extraction(
                        previous,
                        spec["version_id"],
                        record.config["source_hash"],
                        AxisSpecification.model_validate(spec["specification"]).profile.fingerprint,
                    ):
                        await self.outcome(context, "skipped")
                        return
                    # Historical files may predate graph ingestion. Persist only the source.
                    await context.assert_lease()
                    await runtime.graph_store.persist_document(document)
                    extractor = self.extractor_factory(runtime, spec, extracting=True)
                    await extractor.extract(document, run_id=record.extraction_run_id)
                    await context.assert_lease()
                    await context.advance("persistence")
                if record.stage == "persistence":
                    artifact = await self.artifacts_factory(runtime).get(
                        document.id, record.extraction_run_id
                    )
                    if artifact is None:
                        raise WorkflowFailure("layer_artifact_missing")
                    extractor = self.extractor_factory(runtime, spec, extracting=False)
                    write_context = await self.persistence.context_for(record)
                    await context.assert_lease()
                    await extractor.persist(artifact, write_context=write_context)
                    await self.outcome(
                        context, "completed" if extractor.write_applied else "superseded"
                    )
        except DocumentNotFoundError:
            await self.outcome(context, "deleted")
        except (WorkflowFailure, LeaseLost, StorageUnavailable):
            raise
        except AxisError as error:
            raise WorkflowFailure(
                error.code,
                retry_delay=2 if error.code in TRANSIENT_AXIS_ERRORS else None,
                retryable=error.code in TRANSIENT_AXIS_ERRORS,
            ) from None
        except Exception as error:
            if str(error) in {"source_changed", "axis_graph_source_changed"}:
                await self.outcome(context, "changed")
                return
            raise self.failure_for(
                error,
                record.stage_attempts,
                "graph" if record.stage == "persistence" else "extraction",
            ) from None
