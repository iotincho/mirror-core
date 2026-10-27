"""Compose explicit extractor commands; only bootstrap builds concrete resources."""

from contextlib import asynccontextmanager

from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.adapters.storage.postgres.extraction_commands import CommandProcessing
from src.bootstrap.database import close_database
from src.bootstrap.extraction import build_emotion_extractor, build_emotions_provider
from src.bootstrap.processing import get_repository
from src.bootstrap.settings import get_settings
from src.bootstrap.workflows import (
    build_document_embedding_extractor,
    close_workflow_providers,
    worker_runtime,
)
from src.core.extractors.contracts import ExtractorProfile
from src.core.extractors.document_embeddings import EMBEDDINGS_PROFILE, EmbeddingConfiguration
from src.core.extractors.emotions import EMOTIONS_PROFILE
from src.use_cases.extraction.run_command import RunExtraction


@asynccontextmanager
async def extractor(runtime, name, specification, *, extracting):
    if name == "document_embeddings":
        yield build_document_embedding_extractor(runtime, specification, extracting=extracting)
        return
    provider = None
    try:
        if extracting:
            settings = get_settings()
            if settings.llm_provider != "openai":
                raise ValueError("emotion_provider_not_supported")
            provider = build_emotions_provider(settings.openai_api_key, settings.openai_model)
        yield build_emotion_extractor(
            runtime.document_store,
            LayerArtifacts(runtime.context.filesystem_root / "layers"),
            runtime.graph_store.database_client,
            provider,
            ExtractorProfile.model_validate(specification["profile"]),
        )
    finally:
        if provider is not None:
            await provider.close()


async def execute(command):
    settings = get_settings()
    configuration = (
        EmbeddingConfiguration(
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
            segmentation_model=settings.openai_model or "unconfigured",
            segmentation_threshold=settings.embedding_segmentation_threshold,
            section_max_tokens=settings.embedding_section_max_tokens,
            section_target_tokens=settings.embedding_section_target_tokens,
        )
        if command.action == "extract" and command.extractor == "document_embeddings"
        else None
    )
    case = RunExtraction(
        CommandProcessing(get_repository()),
        worker_runtime,
        lambda runtime: LayerArtifacts(runtime.context.filesystem_root / "layers"),
        extractor,
        configuration.model_dump() if configuration else {},
        {
            "emotions": EMOTIONS_PROFILE.model_dump(),
            "document_embeddings": EMBEDDINGS_PROFILE.model_dump(),
        },
    )
    return await case.execute(command)


async def close():
    try:
        await close_workflow_providers()
    finally:
        await close_database()


def main():
    from src.adapters.access.cli.extraction import main as run

    run(execute, close)


if __name__ == "__main__":
    main()
