"""Compose production use cases with fresh workspace credentials and pinned config."""

from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from src.adapters.storage.arcadedb.document_embeddings import ArcadeDBDocumentEmbeddingStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap.audio import build_audio_processor as ProcessAudioNote
from src.bootstrap.audio import build_transcriber as OpenAITranscriptionProvider
from src.bootstrap.documents import build_document_title_extractor as compose_title_extractor
from src.bootstrap.documents import build_title_provider as OpenAIDocumentTitleProvider
from src.bootstrap.extraction import (
    build_document_embeddings_provider as OpenAIDocumentEmbeddingProvider,
)
from src.bootstrap.extraction import build_embedding_extractor as DocumentEmbeddingExtractor
from src.bootstrap.extraction import build_emotion_extractor as EmotionExtractor
from src.bootstrap.extraction import build_emotions_provider as OpenAIEmotionProvider
from src.bootstrap.extractor_registry import ExtractorRegistry
from src.bootstrap.workspaces import build_workspace_runtime, workspace_access, workspace_binding
from src.config import get_settings
from src.core.extractors.contracts import ExtractorProfile
from src.core.extractors.document_embeddings import EmbeddingConfiguration
from src.core.processing.errors import WorkflowFailure
from src.core.workspaces.errors import WorkspaceSecretError
from src.core.workspaces.models import WorkspaceUnavailable
from src.extractors.personal_axes.dependencies import (
    build_personal_axis_extractor,
    close_axis_providers,
    get_axis_provider,
)
from src.use_cases.process_document import ProcessDocument
from src.use_cases.process_document_extractors import ProcessDocumentExtractors
from src.use_cases.process_document_layers import ProcessDocumentLayers
from src.use_cases.process_extractor import ProcessExtractor


@asynccontextmanager
async def worker_runtime(user_id: UUID):
    settings = get_settings()
    try:
        resolved = await workspace_access(settings=settings).resolve(user_id)
    except WorkspaceUnavailable as error:
        if isinstance(error.__cause__, WorkspaceSecretError):
            raise error.__cause__
        raise WorkflowFailure("workspace_unavailable") from error
    binding = workspace_binding(resolved, settings)
    runtime = build_workspace_runtime(binding, settings)
    try:
        yield runtime
    finally:
        await runtime.graph_store.close()


_provider_instances = []


@lru_cache(maxsize=32)
def workflow_providers_configured(transcription_model):
    settings = get_settings()
    if not settings.openai_api_key:
        raise WorkflowFailure("provider_configuration", retryable=True)
    provider = OpenAITranscriptionProvider(
        settings.openai_api_key, transcription_model, max_retries=0
    )
    _provider_instances.append(provider)
    return provider


def workflow_providers(config):
    return workflow_providers_configured(config["transcription_model"])


@lru_cache(maxsize=32)
def emotion_provider_configured(provider_name, model):
    settings = get_settings()
    if provider_name != "openai" or not model or not settings.openai_api_key:
        raise WorkflowFailure("provider_configuration", retryable=True)
    provider = OpenAIEmotionProvider(settings.openai_api_key, model, max_retries=0)
    _provider_instances.append(provider)
    return provider


def build_emotion_extractor(runtime, specification, *, extracting):
    return EmotionExtractor(
        documents=runtime.document_store,
        artifacts=LayerArtifacts(runtime.context.filesystem_root / "layers"),
        graph=runtime.graph_store.database_client,
        profile=ExtractorProfile.model_validate(specification["profile"]),
        provider=emotion_provider_configured(specification["provider"], specification["model"])
        if extracting
        else None,
    )


@lru_cache(maxsize=32)
def embedding_provider_configured(segmentation_model):
    settings = get_settings()
    provider = OpenAIDocumentEmbeddingProvider(settings.openai_api_key, segmentation_model)
    _provider_instances.append(provider)
    return provider


def build_document_embedding_extractor(runtime, specification, *, extracting):
    configuration = EmbeddingConfiguration.model_validate(specification["configuration"])
    return DocumentEmbeddingExtractor(
        documents=runtime.document_store,
        artifacts=LayerArtifacts(runtime.context.filesystem_root / "layers"),
        store=ArcadeDBDocumentEmbeddingStore(runtime.graph_store.database_client),
        configuration=configuration,
        profile=ExtractorProfile.model_validate(specification["profile"]),
        force=specification.get("force", False),
        provider=embedding_provider_configured(configuration.segmentation_model)
        if extracting
        else None,
    )


@lru_cache(maxsize=32)
def title_provider_configured(provider_name, model):
    if provider_name != "openai":
        raise WorkflowFailure("provider_configuration", retryable=True)
    # Credentials are checked only if generation is needed. Imported titles require no LLM.
    provider = OpenAIDocumentTitleProvider(get_settings().openai_api_key, model, max_retries=0)
    _provider_instances.append(provider)
    return provider


def build_document_title_extractor(runtime, specification, *, extracting):
    provider = (
        title_provider_configured(specification["provider"], specification["model"])
        if extracting
        else None
    )
    return compose_title_extractor(runtime, specification, provider=provider)


_extractor_registry = ExtractorRegistry()
_extractor_registry.register("emotions", build_emotion_extractor)
_extractor_registry.register("document_embeddings", build_document_embedding_extractor)
_extractor_registry.register("document_title", build_document_title_extractor)
_extractor_registry.register("personal_axis", build_personal_axis_extractor)


def workflow_extractor(runtime, specification, *, extracting):
    try:
        return _extractor_registry.create(
            specification["name"],
            runtime=runtime,
            specification=specification,
            extracting=extracting,
        )
    except ValueError as error:
        raise WorkflowFailure("extractor_configuration") from error


async def close_workflow_providers():
    try:
        await close_axis_providers()
        for provider in _provider_instances:
            await provider.close()
    finally:
        _provider_instances.clear()
        workflow_providers_configured.cache_clear()
        emotion_provider_configured.cache_clear()
        embedding_provider_configured.cache_clear()
        title_provider_configured.cache_clear()


async def retired_extraction(context):
    raise WorkflowFailure("extraction_retired")


def register_workflows(registry):
    # Old messages cannot recreate historical extractions after the cutover.
    from src.bootstrap.invitations import get_send_invitation
    from src.bootstrap.recovery import get_send_recovery_email
    from src.core.processing.workflows import WorkflowDefinition
    from src.use_cases.process_axis_history import ProcessAxisHistory
    from src.use_cases.process_axis_preview import ProcessAxisPreview
    from src.use_cases.processing.context import ExecutionContext

    registry.register(
        "axis_history_note", 1, ProcessAxisHistory(worker_runtime, workflow_extractor).definition
    )
    registry.register(
        "axis_preview", 1, ProcessAxisPreview(worker_runtime, get_axis_provider).definition
    )

    async def send_invitation(context: ExecutionContext) -> None:
        await get_send_invitation().execute(context)

    async def send_recovery_email(context: ExecutionContext) -> None:
        await get_send_recovery_email().execute(context)

    registry.register(
        "password_recovery_email",
        1,
        WorkflowDefinition(send_recovery_email, frozenset(), requires_workspace=False),
    )

    registry.register("invitation_push", 1, WorkflowDefinition(send_invitation, frozenset()))
    registry.register("document", 1, WorkflowDefinition(retired_extraction, frozenset()))
    registry.register("document", 2, ProcessDocument(worker_runtime).definition)
    registry.register(
        "document", 3, ProcessDocumentLayers(worker_runtime, workflow_extractor).definition
    )
    registry.register("document", 4, ProcessDocumentExtractors(worker_runtime).definition)
    registry.register(
        "document", 5, ProcessDocumentExtractors(worker_runtime, keyed=True).definition
    )
    registry.register(
        "extractor", 1, ProcessExtractor(worker_runtime, workflow_extractor).definition
    )
    # Audio reuses its transcript and passes the accepted layer configuration to its child.
    registry.register("audio", 1, ProcessAudioNote(worker_runtime, workflow_providers).definition)
    registry.register("audio", 2, ProcessAudioNote(worker_runtime, workflow_providers).definition)
