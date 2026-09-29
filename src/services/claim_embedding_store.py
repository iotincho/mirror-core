"""Port for durable vectors and semantic retrieval of extracted claims."""

from typing import Protocol

from src.embeddings.contracts import ClaimEmbeddingRecord, EmbeddingSpec, SimilarClaim


class ClaimEmbeddingStoreError(RuntimeError):
    """Raised when claim vectors cannot be persisted or queried."""


class ClaimEmbeddingStore(Protocol):
    """Database-independent boundary for claim vector persistence and retrieval."""

    def persist_claim_embeddings(
        self,
        records: list[ClaimEmbeddingRecord],
        spec: EmbeddingSpec,
    ) -> None:
        """Store embeddings and ensure a vector index for their exact specification."""

    def search_claim_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarClaim]:
        """Return claims nearest to a query embedding, with evidence references."""
