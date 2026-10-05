"""Provider-neutral port for producing a validated extraction result."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.domain.documents import Document
from src.extraction.contracts import ExtractionResult
from src.extraction.profiles import ExtractionProfile


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderExtraction(BaseModel):
    """Normalized metadata from a provider without exposing its SDK types."""

    model_config = ConfigDict(frozen=True)

    result: ExtractionResult
    provider: str
    model: str
    response_id: str | None = None
    usage: TokenUsage = TokenUsage()


class StructuredExtractor(Protocol):
    """Port implemented by OpenAI today and local providers later."""

    provider_name: str
    model_name: str

    async def extract(self, document: Document, profile: ExtractionProfile) -> ProviderExtraction:
        """Extract a result from one original document."""


    async def close(self) -> None:
        """Release owned provider resources before stopping the event loop."""

class ExtractionProviderError(RuntimeError):
    """Raised when a configured provider cannot produce a valid structured response."""


class UnavailableStructuredExtractor:
    """Placeholder for a provider selected in configuration but not implemented yet."""

    def __init__(self, provider_name: str, model_name: str = "unconfigured") -> None:
        self.provider_name = provider_name
        self.model_name = model_name

    async def extract(self, document: Document, profile: ExtractionProfile) -> ProviderExtraction:
        raise ExtractionProviderError(f"Provider {self.provider_name} is not implemented")

    async def close(self) -> None:
        """This unavailable adapter owns no connections."""
