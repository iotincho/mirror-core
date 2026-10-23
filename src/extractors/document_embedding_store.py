"""Compatibility imports; use the canonical layers for new code."""

from src.adapters.storage.arcadedb.document_embeddings import (
    ArcadeDBDocumentEmbeddingStore as ArcadeDBDocumentEmbeddingStore,
)
from src.core.extractors.document_embeddings import DocumentEmbeddingStore as DocumentEmbeddingStore
from src.core.extractors.document_embeddings import MatchingSection as MatchingSection
from src.core.extractors.document_embeddings import SimilarDocument as SimilarDocument
