"""Semantic claim retrieval without generating a reflective answer yet."""

import logging

from src.embeddings.contracts import SimilarClaim
from src.services.claim_embedding_store import ClaimEmbeddingStore, ClaimEmbeddingStoreError
from src.services.embedding_provider import EmbeddingProvider, EmbeddingProviderError

logger = logging.getLogger(__name__)


class SemanticSearchFailedError(RuntimeError):
    """Signals an embedding or vector-store failure during semantic retrieval."""


class SearchSimilarClaims:
    """Find evidence-backed claims related to a natural-language query."""

    def __init__(self, provider: EmbeddingProvider, store: ClaimEmbeddingStore) -> None:
        self._provider = provider
        self._store = store

    async def execute(self, query: str, limit: int = 10) -> list[SimilarClaim]:
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("query must not be blank and limit must be between 1 and 50")
        try:
            logger.info(
                "semantic_claim_search_started query_length=%s limit=%s",
                len(query),
                limit,
            )
            vectors = await self._provider.embed([query])
            if len(vectors) != 1:
                raise EmbeddingProviderError("Provider returned an unexpected number of embeddings")
            vector = vectors[0]
            results = await self._store.search_claim_embeddings(vector.vector, vector.spec, limit)
            logger.info(
                "semantic_claim_search_completed limit=%s result_count=%s provider=%s "
                "model=%s dimensions=%s",
                limit,
                len(results),
                vector.spec.provider,
                vector.spec.model,
                vector.spec.dimensions,
            )
            return results
        except (EmbeddingProviderError, ClaimEmbeddingStoreError) as error:
            logger.exception(
                "semantic_claim_search_failed query_length=%s limit=%s error_type=%s",
                len(query),
                limit,
                type(error).__name__,
            )
            raise SemanticSearchFailedError("Semantic claim search failed") from error
