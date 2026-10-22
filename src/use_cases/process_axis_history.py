"""One historical note reuses the extractor lifecycle and durable checkpoints."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import content_hash
from src.extractors.personal_axes.contracts import AxisError, AxisSpecification
from src.extractors.personal_axes.history import AxisHistory, current_extraction
from src.extractors.personal_axes.history_models import AxisHistoryBatch, AxisHistoryItem
from src.extractors.personal_axes.persistence import bind_axis_write
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for
from src.services.document_store import DocumentNotFoundError
from src.use_cases.axis_previews import AxisPreviews


class ProcessAxisHistory:
    transitions = frozenset(
        {("extraction", "persistence"), ("extraction", "done"), ("persistence", "done")}
    )

    def __init__(self, runtime_factory, extractor_factory):
        self.runtime_factory, self.extractor_factory = runtime_factory, extractor_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def outcome(self, context, value):
        async with context.repository.leased(context.record) as (session, _, _):
            item = await session.get(
                AxisHistoryItem,
                (UUID(context.record.config["batch_id"]), context.record.resource_id),
                with_for_update=True,
            )
            item.outcome = value
        if context.record.stage != "done":
            await context.advance("done")

    async def execute(self, context):
        record = context.record
        try:
            async with context.repository.sessions.begin() as session:
                batch = await session.scalar(
                    select(AxisHistoryBatch)
                    .where(
                        AxisHistoryBatch.id == UUID(record.config["batch_id"]),
                        AxisHistoryBatch.user_id == record.user_id,
                    )
                    .with_for_update()
                )
                if batch is None:
                    raise WorkflowFailure("axis_history_not_found")
                item = await session.get(
                    AxisHistoryItem, (batch.id, record.resource_id), with_for_update=True
                )
                if item is None or item.processing_id != record.id:
                    raise WorkflowFailure("axis_history_item_mismatch")
                skip = item.outcome is not None or (
                    batch.stopped_at is not None and item.started_at is None
                )
                if not skip and item.started_at is None:
                    item.started_at = await session.scalar(select(func.clock_timestamp()))
            if skip:
                await self.outcome(context, item.outcome or "stopped")
                return
            async with self.runtime_factory(record.user_id) as runtime:
                document = await runtime.document_store.get(record.resource_id)
                if content_hash(document.content) != record.config["source_hash"]:
                    await self.outcome(context, "changed")
                    return
                spec = record.config["extractor"]
                if record.stage == "extraction":
                    history = AxisHistory(AxisPreviews(context.repository, runtime, get_settings()))
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
                    artifact = await LayerArtifacts(runtime.context.filesystem_root / "layers").get(
                        document.id, record.extraction_run_id
                    )
                    if artifact is None:
                        raise WorkflowFailure("layer_artifact_missing")
                    extractor = self.extractor_factory(runtime, spec, extracting=False)
                    await bind_axis_write(extractor, context.repository.sessions, record)
                    await context.assert_lease()
                    await extractor.persist(artifact)
                    await self.outcome(
                        context, "completed" if extractor.write_applied else "superseded"
                    )
        except DocumentNotFoundError:
            await self.outcome(context, "deleted")
        except (WorkflowFailure, LeaseLost, SQLAlchemyError):
            raise
        except AxisError as error:
            raise WorkflowFailure(
                error.code,
                retry_delay=2 if error.status == 503 else None,
                retryable=error.status == 503,
            ) from None
        except Exception as error:
            if str(error) in {"source_changed", "axis_graph_source_changed"}:
                await self.outcome(context, "changed")
                return
            raise failure_for(
                error,
                record.stage_attempts,
                "graph" if record.stage == "persistence" else "extraction",
            ) from None
