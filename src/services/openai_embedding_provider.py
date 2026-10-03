"""OpenAI implementation of the embedding-provider port."""

import logging
from time import perf_counter
from typing import Any

from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector
from src.services.embedding_provider import EmbeddingProviderError
from src.services.provider_diagnostics import provider_error_details

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider:
    """Generate configured-dimension vectors through the OpenAI Embeddings API."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        dimensions: int,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self.spec = EmbeddingSpec(provider="openai", model=model, dimensions=dimensions)
        self._client = client

    def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        started = perf_counter()
        stage = "configuration"
        try:
            if not texts or any(not text.strip() for text in texts):
                raise EmbeddingProviderError("Embedding inputs must be non-empty")
            client = self._get_client()
            stage = "request"
            logger.info(
                "openai_embedding_request_started input_count=%s model=%s dimensions=%s",
                len(texts),
                self.spec.model,
                self.spec.dimensions,
            )
            response = client.embeddings.create(
                model=self.spec.model,
                input=texts,
                dimensions=self.spec.dimensions,
                encoding_format="float",
            )
            stage = "response_validation"
            vectors = [
                list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)
            ]
            if len(vectors) != len(texts) or any(
                len(vector) != self.spec.dimensions for vector in vectors
            ):
                raise EmbeddingProviderError(
                    "OpenAI returned unexpected embeddings: "
                    f"expected_count={len(texts)} actual_count={len(vectors)} "
                    f"expected_dimensions={self.spec.dimensions} "
                    f"actual_dimensions={sorted({len(vector) for vector in vectors})}"
                )
        except Exception as error:
            logger.exception(
                "openai_embedding_request_failed input_count=%s model=%s dimensions=%s "
                "stage=%s duration_ms=%.1f diagnostics=%s",
                len(texts),
                self.spec.model,
                self.spec.dimensions,
                stage,
                (perf_counter() - started) * 1000,
                provider_error_details(error),
            )
            if isinstance(error, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError("OpenAI embedding request failed") from error
        usage = getattr(response, "usage", None)
        logger.info(
            "openai_embedding_request_completed input_count=%s model=%s dimensions=%s "
            "input_tokens=%s upstream_request_id=%s duration_ms=%.1f",
            len(texts),
            getattr(response, "model", self.spec.model),
            len(vectors[0]) if vectors else 0,
            getattr(usage, "prompt_tokens", None),
            getattr(response, "_request_id", None),
            (perf_counter() - started) * 1000,
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

        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
