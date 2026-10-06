"""Semantic retrieval that returns both original documents and extracted claims."""

import logging

from src.embeddings.contracts import SearchResult
from src.services.claim_embedding_store import ClaimEmbeddingStore, ClaimEmbeddingStoreError
from src.services.document_embedding_store import (
    DocumentEmbeddingStore,
    DocumentEmbeddingStoreError,
)
from src.services.embedding_provider import EmbeddingProvider, EmbeddingProviderError

logger = logging.getLogger(__name__)


class SemanticSearchFailedError(RuntimeError):
    """Signals an embedding or vector-store failure during semantic retrieval."""


class SearchSemantically:
    """Find semantically close source documents and their evidence-backed claims."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        claim_store: ClaimEmbeddingStore,
        document_store: DocumentEmbeddingStore,
    ) -> None:
        self._provider = provider
        self._claim_store = claim_store
        self._document_store = document_store

    async def execute(self, query: str, limit: int = 10) -> list[SearchResult]:
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("query must not be blank and limit must be between 1 and 50")
        try:
            vectors = await self._provider.embed([query])
            if len(vectors) != 1:
                raise EmbeddingProviderError("Provider returned an unexpected number of embeddings")
            query_vector = vectors[0]
            claims = await self._claim_store.search_claim_embeddings(
                query_vector.vector, query_vector.spec, limit
            )
            documents = await self._document_store.search_document_embeddings(
                query_vector.vector, query_vector.spec, limit
            )
            return sorted([*claims, *documents], key=lambda item: item.score, reverse=True)[:limit]
        except (
            EmbeddingProviderError,
            ClaimEmbeddingStoreError,
            DocumentEmbeddingStoreError,
        ) as error:
            logger.exception("semantic_search_failed query_length=%s", len(query))
            raise SemanticSearchFailedError("Semantic search failed") from error
