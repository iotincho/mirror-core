"""Compose emotion and embedding algorithms with technical persistence/provider adapters."""

from src.adapters.providers.openai.document_embeddings import OpenAIDocumentEmbeddingProvider
from src.adapters.providers.openai.emotions import OpenAIEmotionProvider
from src.adapters.providers.openai.tokenization import token_count
from src.adapters.storage.arcadedb.emotions import ArcadeDBEmotionStore
from src.bootstrap.settings import get_settings
from src.core.extractors.document_embeddings import EMBEDDINGS_PROFILE
from src.core.extractors.emotions import EMOTIONS_PROFILE
from src.use_cases.extraction.document_embeddings import DocumentEmbeddingExtractor
from src.use_cases.extraction.emotions import EmotionExtractor


def build_emotion_extractor(documents, artifacts, graph, provider=None, profile=EMOTIONS_PROFILE):
    return EmotionExtractor(documents, artifacts, ArcadeDBEmotionStore(graph), provider, profile)


def build_embedding_extractor(
    documents,
    artifacts,
    store,
    configuration,
    provider=None,
    profile=EMBEDDINGS_PROFILE,
    force=False,
):
    return DocumentEmbeddingExtractor(
        documents,
        artifacts,
        store,
        configuration,
        provider,
        profile,
        force,
        token_count=token_count,
    )


def build_emotions_provider(api_key, model, client=None, *, max_retries=2):
    settings = get_settings()
    return OpenAIEmotionProvider(
        api_key,
        model,
        client,
        timeout_seconds=settings.provider_timeout_seconds,
        max_concurrency=settings.provider_max_concurrency,
        max_retries=max_retries,
    )


def build_document_embeddings_provider(api_key, segmentation_model, client=None, *, max_retries=0):
    settings = get_settings()
    return OpenAIDocumentEmbeddingProvider(
        api_key,
        segmentation_model,
        client,
        timeout_seconds=settings.provider_timeout_seconds,
        max_concurrency=settings.provider_max_concurrency,
        max_retries=max_retries,
    )
