"""Compose production use cases with fresh workspace credentials and pinned config."""

from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from src.config import get_settings
from src.processing.execution import WorkflowFailure
from src.services.openai_embedding_provider import OpenAIEmbeddingProvider
from src.services.openai_extractor import OpenAIExtractor
from src.services.openai_transcription_provider import OpenAITranscriptionProvider
from src.use_cases.process_audio_note import ProcessAudioNote
from src.use_cases.process_document import ProcessDocument
from src.user_management.database import get_session_maker
from src.workspaces.context import UserWorkspaceContext
from src.workspaces.dependencies import WorkspaceBinding, build_workspace_runtime
from src.workspaces.models import UserWorkspace
from src.workspaces.secrets import WorkspaceSecretCipher


@asynccontextmanager
async def worker_runtime(user_id: UUID):
    settings = get_settings()
    async with get_session_maker()() as session:
        workspace = await session.get(UserWorkspace, user_id)
        if (
            workspace is None
            or workspace.status != "active"
            or workspace.arcadedb_instance_key != settings.arcadedb_instance_key
        ):
            raise WorkflowFailure("workspace_unavailable")
        secret = WorkspaceSecretCipher(settings).decrypt(workspace.graph_secret_ciphertext)
        binding = WorkspaceBinding(
            UserWorkspaceContext(
                user_id=user_id,
                arcadedb_instance_key=workspace.arcadedb_instance_key,
                database_name=workspace.database_name,
                graph_username=workspace.graph_username,
                filesystem_root=settings.workspaces_path / str(user_id),
            ),
            secret,
        )
    runtime = build_workspace_runtime(binding, settings)
    try:
        yield runtime
    finally:
        await runtime.graph_store.close()


_provider_instances = []


@lru_cache(maxsize=32)
def providers_for(llm_model, transcription_model, embedding_model, dimensions):
    settings = get_settings()
    if not settings.openai_api_key or llm_model == "unconfigured":
        raise WorkflowFailure("provider_configuration", retryable=True)
    providers = (
        OpenAIExtractor(settings.openai_api_key, llm_model, max_retries=0),
        OpenAITranscriptionProvider(settings.openai_api_key, transcription_model, max_retries=0),
        OpenAIEmbeddingProvider(
            settings.openai_api_key, embedding_model, dimensions, max_retries=0
        ),
    )
    _provider_instances.extend(providers)
    return providers


def workflow_providers(config):
    if config["llm_provider"] != "openai" or config["embedding_provider"] != "openai":
        raise WorkflowFailure("provider_configuration", retryable=True)
    return providers_for(
        config["llm_model"],
        config["transcription_model"],
        config["embedding_model"],
        config["embedding_dimensions"],
    )


async def close_workflow_providers():
    try:
        for provider in _provider_instances:
            await provider.close()
    finally:
        _provider_instances.clear()
        providers_for.cache_clear()


def register_workflows(registry):
    registry.register("document", 1, ProcessDocument(worker_runtime, workflow_providers).definition)
    registry.register("audio", 1, ProcessAudioNote(worker_runtime, workflow_providers).definition)
