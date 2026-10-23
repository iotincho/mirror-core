"""Compatibility imports; use the canonical layers for new code."""

from src.adapters.providers.openai.tokenization import token_count as token_count
from src.core.extractors.document_embeddings import EMBEDDINGS_PROFILE as EMBEDDINGS_PROFILE
from src.core.extractors.document_embeddings import BlockRange as BlockRange
from src.core.extractors.document_embeddings import (
    DocumentEmbeddingProvider as DocumentEmbeddingProvider,
)
from src.core.extractors.document_embeddings import DocumentEmbeddings as DocumentEmbeddings
from src.core.extractors.document_embeddings import EmbeddingConfiguration as EmbeddingConfiguration
from src.core.extractors.document_embeddings import EmbeddingSection as EmbeddingSection
from src.core.extractors.document_embeddings import Segmentation as Segmentation


def bounded_spans(text, maximum):
    from src.use_cases.extraction.document_embeddings import bounded_spans as spans

    return spans(text, maximum, token_count)


def DocumentEmbeddingExtractor(
    documents,
    artifacts,
    store,
    configuration,
    provider=None,
    profile=EMBEDDINGS_PROFILE,
    force=False,
):
    from src.bootstrap.extraction import build_embedding_extractor

    return build_embedding_extractor(
        documents, artifacts, store, configuration, provider, profile, force
    )
