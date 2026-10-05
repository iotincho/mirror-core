"""Provider port for structured, evidence-bound reflection."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.reflection.contracts import ReflectionContext, ReflectionResult
from src.reflection.profiles import ReflectionProfile
from src.services.structured_extractor import TokenUsage


class ProviderReflection(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: ReflectionResult
    provider: str
    model: str
    response_id: str | None = None
    usage: TokenUsage = TokenUsage()


class ReflectionProvider(Protocol):
    provider_name: str
    model_name: str

    async def reflect(
        self, context: ReflectionContext, profile: ReflectionProfile
    ) -> ProviderReflection: ...


    async def close(self) -> None:
        """Release owned provider resources before stopping the event loop."""

class ReflectionProviderError(RuntimeError):
    """Raised when a reflection provider cannot produce a usable answer."""


class UnavailableReflectionProvider:
    def __init__(self, provider_name: str, model_name: str = "unconfigured") -> None:
        self.provider_name = provider_name
        self.model_name = model_name

    async def reflect(
        self, context: ReflectionContext, profile: ReflectionProfile
    ) -> ProviderReflection:
        raise ReflectionProviderError(f"Provider {self.provider_name} is not implemented")

    async def close(self) -> None:
        """This unavailable adapter owns no connections."""
