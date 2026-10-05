"""OpenAI implementation of the embedding-provider port."""

import logging
from typing import Any

from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector
from src.services.async_provider import AsyncProvider
from src.services.embedding_provider import EmbeddingProviderError

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(AsyncProvider):
    """Generate configured-dimension vectors through the OpenAI Embeddings API."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        dimensions: int,
        client: Any | None = None,
        *,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self.spec = EmbeddingSpec(provider="openai", model=model, dimensions=dimensions)
        self._configure_client(client)
        self._sdk_max_retries = max_retries

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingProviderError("Embedding inputs must be non-empty")
        client = self._get_client()
        try:
            logger.info(
                "openai_embedding_request_started input_count=%s model=%s dimensions=%s",
                len(texts),
                self.spec.model,
                self.spec.dimensions,
            )
            async with self._request_slot():
                response = await client.embeddings.create(
                    model=self.spec.model,
                    input=texts,
                    dimensions=self.spec.dimensions,
                    encoding_format="float",
                )
        except Exception as error:
            logger.exception(
                "openai_embedding_request_failed input_count=%s model=%s dimensions=%s "
                "error_type=%s",
                len(texts),
                self.spec.model,
                self.spec.dimensions,
                type(error).__name__,
            )
            raise EmbeddingProviderError("OpenAI embedding request failed") from error

        vectors = [
            list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)
        ]
        if len(vectors) != len(texts) or any(
            len(vector) != self.spec.dimensions for vector in vectors
        ):
            raise EmbeddingProviderError("OpenAI returned embeddings with unexpected dimensions")
        usage = getattr(response, "usage", None)
        logger.info(
            "openai_embedding_request_completed input_count=%s model=%s dimensions=%s "
            "input_tokens=%s",
            len(texts),
            getattr(response, "model", self.spec.model),
            len(vectors[0]) if vectors else 0,
            getattr(usage, "prompt_tokens", None),
        )
        return [
            EmbeddingVector(
                vector=vector,
                spec=EmbeddingSpec(
                    provider="openai",
                    model=getattr(response, "model", self.spec.model),
                    dimensions=len(vector),
                ),
                input_tokens=getattr(usage, "prompt_tokens", None),
            )
            for vector in vectors
        ]

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise EmbeddingProviderError("OpenAI embeddings require OPENAI_API_KEY")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=self._api_key, timeout=self._timeout, max_retries=self._sdk_max_retries
        )
        return self._client
