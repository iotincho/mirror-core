"""Port for durable vectors and semantic retrieval of original documents."""

from typing import Protocol

from src.embeddings.contracts import DocumentEmbeddingRecord, EmbeddingSpec, SimilarDocument


class DocumentEmbeddingStoreError(RuntimeError):
    """Raised when document vectors cannot be persisted or queried."""


class DocumentEmbeddingStore(Protocol):
    """Database-independent boundary for document vector persistence and retrieval."""

    async def persist_document_embedding(
        self,
        record: DocumentEmbeddingRecord,
        spec: EmbeddingSpec,
    ) -> None:
        """Store one document vector and ensure a vector index for its specification."""

    async def search_document_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarDocument]:
        """Return documents nearest to a query embedding."""
