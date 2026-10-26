"""Pilot composition and explicit bridges to the unmigrated durable coordinator."""

from src.adapters.providers.openai.document_title import OpenAIDocumentTitleProvider
from src.adapters.storage.arcadedb.document_titles import ArcadeDBDocumentTitleStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap.settings import get_settings
from src.core.documents.title_scheduling import TitleReadPolicy
from src.core.extractors.contracts import ExtractorProfile
from src.use_cases.documents.ensure_document_titles import EnsureDocumentTitles
from src.use_cases.extraction.document_title import DocumentTitleExtractor


def build_title_provider(api_key, model, client=None, *, max_retries=2):
    settings = get_settings()
    return OpenAIDocumentTitleProvider(
        api_key,
        model,
        client,
        timeout_seconds=settings.provider_timeout_seconds,
        max_concurrency=settings.provider_max_concurrency,
        max_retries=max_retries,
    )


def build_document_title_extractor(runtime, specification, *, provider=None):
    # Workspace ownership and the accepted specification are supplied by the current runner.
    return DocumentTitleExtractor(
        documents=runtime.document_store,
        artifacts=LayerArtifacts(runtime.context.filesystem_root / "layers"),
        store=ArcadeDBDocumentTitleStore(runtime.graph_store.database_client),
        profile=ExtractorProfile.model_validate(specification["profile"]),
        provider=provider,
    )


def build_title_scheduler(repository, runtime):
    from src.bootstrap.processing import build_title_backfill

    settings = get_settings()
    policy = TitleReadPolicy(
        limit=settings.document_title_read_limit,
        enabled=bool(
            settings.llm_provider == "openai" and settings.openai_model and settings.openai_api_key
        ),
    )
    return EnsureDocumentTitles(build_title_backfill(repository, runtime), policy)
