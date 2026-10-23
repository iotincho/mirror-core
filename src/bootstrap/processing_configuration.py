"""Snapshot provider choices and profiles from explicit environment settings."""

from src.core.extractors.document_embeddings import EMBEDDINGS_PROFILE, EmbeddingConfiguration
from src.core.extractors.document_title import TITLE_PROFILE
from src.core.extractors.emotions import EMOTIONS_PROFILE


def document_title_specification(settings):
    return {
        "name": "document_title",
        "profile": TITLE_PROFILE.model_dump(mode="json"),
        "provider": settings.llm_provider,
        "model": settings.openai_model,
    }


def workflow_config(settings):
    return {
        "transcription_model": settings.openai_transcription_model,
        "document_workflow_version": 4,
        "extractors": [
            {
                "name": "emotions",
                "profile": EMOTIONS_PROFILE.model_dump(mode="json"),
                "provider": settings.llm_provider,
                "model": settings.openai_model,
            },
            {
                "name": "document_embeddings",
                "profile": EMBEDDINGS_PROFILE.model_dump(mode="json"),
                "configuration": EmbeddingConfiguration(
                    model=settings.openai_embedding_model,
                    dimensions=settings.openai_embedding_dimensions,
                    segmentation_model=settings.openai_model or "unconfigured",
                    segmentation_threshold=settings.embedding_segmentation_threshold,
                    section_max_tokens=settings.embedding_section_max_tokens,
                    section_target_tokens=settings.embedding_section_target_tokens,
                ).model_dump(mode="json"),
                "force": False,
            },
            document_title_specification(settings),
        ],
    }
