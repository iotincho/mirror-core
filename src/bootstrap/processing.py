"""Process-local durable composition through canonical state and application ports."""

from contextlib import asynccontextmanager
from functools import lru_cache

from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.state import PostgresExecutionStore, database_errors
from src.bootstrap.database import get_session_maker
from src.bootstrap.observability import report_issue
from src.bootstrap.settings import get_settings
from src.use_cases.processing.execute import ExecuteProcessing


def build_executor(repository, registry, max_attempts=4):
    if isinstance(repository, PostgresExecutionStore):
        store = repository
    else:
        store = PostgresExecutionStore(repository)
    return ExecuteProcessing(store, registry, max_attempts, report_issue=report_issue)


@lru_cache
def get_repository() -> ProcessingRepository:
    return ProcessingRepository(get_session_maker(), get_settings().processing_lease_seconds)


def get_executor():
    from src.bootstrap.workflow_registry import registry

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


def extractor_failure(error, record, service):
    from src.bootstrap.failures import failure_for
    from src.core.extractors.personal_axes.policies import extraction_failure
    from src.core.processing.errors import FailureDecision

    failure = failure_for(error, record.stage_attempts, service)
    policies = {"personal_axis": extraction_failure}
    policy = policies.get(record.extractor_name)
    return policy(error, failure) if policy else FailureDecision(failure)


def build_extractor_processor(runtime_factory, extractor_factory, *, repository=None):
    from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
    from src.use_cases.processing.process_extractor import ProcessExtractor

    async def persist_extraction(extractor, output, record):
        from src.adapters.storage.postgres.personal_axes.write_contexts import (
            PostgresAxisWriteContexts,
        )
        from src.use_cases.personal_axes.persist import PersistPersonalAxis

        if record.extractor_name == "personal_axis":
            case = PersistPersonalAxis(
                PostgresAxisWriteContexts((repository or get_repository()).sessions)
            )
            await case.execute(extractor, output, record)
        else:
            await extractor.persist(output)

    return ProcessExtractor(
        protected_runtime(runtime_factory),
        extractor_factory,
        artifacts_factory=lambda runtime: LayerArtifacts(
            runtime.context.filesystem_root / "layers"
        ),
        persist_extraction=persist_extraction,
        failure_for=extractor_failure,
    )


def requests_store(repository):
    from src.adapters.storage.postgres.transactions import PostgresProcessingRequests
    from src.bootstrap.personal_axes import user_workflow_config

    return PostgresProcessingRequests(repository, config_factory=user_workflow_config)


def build_processing_requests(repository, runtime):
    from src.bootstrap.acceptance import workflow_config
    from src.use_cases.processing.request_processing import RequestProcessing

    return RequestProcessing(requests_store(repository), runtime, workflow_config=workflow_config)


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
