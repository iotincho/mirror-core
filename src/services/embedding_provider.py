"""Port for generating vectors without coupling use cases to one provider."""

from typing import Protocol

from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector


class EmbeddingProviderError(RuntimeError):
    """Raised when a configured provider cannot generate embeddings."""


class EmbeddingProvider(Protocol):
    """Provider port implemented by OpenAI today and local engines later."""

    spec: EmbeddingSpec

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        """Create one vector for each non-empty input, in the original order."""


    async def close(self) -> None:
        """Release owned provider resources before stopping the event loop."""

class UnavailableEmbeddingProvider:
    """Placeholder for a configured local provider not implemented yet."""

    def __init__(self, provider: str, model: str, dimensions: int) -> None:
        self.spec = EmbeddingSpec(provider=provider, model=model, dimensions=dimensions)

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        raise EmbeddingProviderError(f"Embedding provider {self.spec.provider} is not implemented")

    async def close(self) -> None:
        """This unavailable adapter owns no connections."""
