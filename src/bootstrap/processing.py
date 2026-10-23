"""Process-local durable composition; legacy workflow SQL stays outside the runner."""

from contextlib import asynccontextmanager
from functools import lru_cache

from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.state import PostgresExecutionStore, database_errors
from src.bootstrap.database import get_session_maker
from src.config import get_settings
from src.core.processing.workflows import WorkflowDefinition, WorkflowRegistry
from src.observability import report_issue
from src.use_cases.processing.context import ExecutionContext
from src.use_cases.processing.execute import ExecuteProcessing


class CompatibleRegistry:
    def __init__(self, registry, repository):
        self.registry, self.repository = registry, repository

    def get(self, record):
        definition = self.registry.get(record)

        async def run(context):
            async with database_errors():
                # Experimental workflows retain their internal SQL behind this exact bridge.
                if record.workflow in {"axis_preview", "axis_history_note"}:
                    context = ExecutionContext(self.repository, context.record, definition)
                await definition.run(context)

        return WorkflowDefinition(run, definition.transitions, definition.requires_workspace)


def build_executor(repository, registry, max_attempts=4):
    if isinstance(repository, PostgresExecutionStore):
        store = repository
    else:
        store = PostgresExecutionStore(repository)
        registry = CompatibleRegistry(registry, repository)
    return ExecuteProcessing(store, registry, max_attempts, report_issue=report_issue)


@lru_cache
def get_repository() -> ProcessingRepository:
    return ProcessingRepository(get_session_maker(), get_settings().processing_lease_seconds)


def get_executor():
    return build_executor(get_repository(), registry)


def protected_runtime(runtime_factory):
    @asynccontextmanager
    async def resolve(user_id):
        async with database_errors(), runtime_factory(user_id) as runtime:
            yield runtime

    return resolve


def build_document_coordinator(runtime_factory, *, keyed=False):
    from src.bootstrap.failures import failure_for
    from src.use_cases.processing.process_document_extractors import ProcessDocumentExtractors

    return ProcessDocumentExtractors(
        protected_runtime(runtime_factory), failure_for=failure_for, keyed=keyed
    )


def build_source_processor(runtime_factory):
    from src.bootstrap.failures import failure_for
    from src.use_cases.processing.process_document import ProcessDocument

    return ProcessDocument(protected_runtime(runtime_factory), failure_for=failure_for)


def build_legacy_layers_processor(runtime_factory, extractor_factory):
    from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
    from src.bootstrap.failures import failure_for
    from src.use_cases.processing.process_document_layers import ProcessDocumentLayers

    return ProcessDocumentLayers(
        protected_runtime(runtime_factory),
        extractor_factory,
        failure_for=failure_for,
        artifacts_factory=lambda runtime: LayerArtifacts(
            runtime.context.filesystem_root / "layers"
        ),
    )


async def prepare_extractor_persistence(extractor, context):
    if context.record.extractor_name == "personal_axis":
        from src.extractors.personal_axes.persistence import bind_axis_write

        # Explicit compatibility with the experimental module; no sessions cross into the
        # generic processor. The concrete adapter and this bridge share their composition root.
        store = context.repository
        repository = store._repository if isinstance(store, PostgresExecutionStore) else store
        async with database_errors():
            await bind_axis_write(extractor, repository.sessions, context.record)


def extractor_failure(error, record, service):
    from src.bootstrap.failures import failure_for
    from src.core.processing.errors import FailureDecision, WorkflowFailure

    failure = failure_for(error, record.stage_attempts, service)
    private = record.extractor_name == "personal_axis"
    if private and "axis_correction_interrupted" in str(error):
        failure = WorkflowFailure("axis_correction_interrupted")
    return FailureDecision(failure, suppress_cause=private)


def build_extractor_processor(runtime_factory, extractor_factory):
    from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
    from src.use_cases.processing.process_extractor import ProcessExtractor

    return ProcessExtractor(
        protected_runtime(runtime_factory),
        extractor_factory,
        artifacts_factory=lambda runtime: LayerArtifacts(
            runtime.context.filesystem_root / "layers"
        ),
        prepare_persistence=prepare_extractor_persistence,
        failure_for=extractor_failure,
    )


def requests_store(repository):
    from src.adapters.storage.postgres.transactions import PostgresProcessingRequests
    from src.extractors.personal_axes.configuration import user_workflow_config

    return PostgresProcessingRequests(repository, config_factory=user_workflow_config)


def build_processing_requests(repository, runtime):
    from src.bootstrap.acceptance import workflow_config
    from src.use_cases.processing.request_processing import RequestProcessing

    return RequestProcessing(requests_store(repository), runtime, workflow_config=workflow_config)


class LegacyRequestFacade:
    """Adapt the history module's existing reset(session, row, now) call only."""

    def __init__(self, repository, runtime):
        self._repository = repository
        self._case = build_processing_requests(repository, runtime)

    def __getattr__(self, name):
        return getattr(self._case, name)

    def reset(self, session, record, now):
        from src.adapters.storage.postgres.transactions import PostgresTransaction
        from src.extractors.personal_axes.configuration import user_workflow_config

        # History owns this transaction. Translate its ORM row once, apply the same pure
        # reset policy, and synchronize into that session without another commit or lock.
        transaction = PostgresTransaction(session, self._repository, now, user_workflow_config)
        state = transaction._track(record)
        self._case.reset(transaction, state, now)
        transaction.synchronize()


def build_title_backfill(repository, runtime):
    from src.bootstrap.acceptance import build_submission_port, document_title_specification
    from src.use_cases.documents.backfill_document_titles import BackfillDocumentTitles

    return BackfillDocumentTitles(
        requests_store(repository),
        runtime,
        submissions=build_submission_port(repository),
        requests=build_processing_requests(repository, runtime),
        title_specification=document_title_specification,
    )


registry = WorkflowRegistry()

from src.bootstrap.workflows import register_workflows  # noqa: E402

register_workflows(registry)
