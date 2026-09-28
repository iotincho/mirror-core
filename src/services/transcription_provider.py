"""Provider boundary for speech-to-text."""

from pathlib import Path
from typing import Protocol


class TranscriptionProviderError(RuntimeError):
    """Raised when a provider cannot produce a usable transcript."""


class TranscriptionProvider(Protocol):
    provider_name: str
    model_name: str

    def transcribe(self, audio_path: Path) -> str: ...


class UnavailableTranscriptionProvider:
    def __init__(self, provider_name: str, model_name: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name

    def transcribe(self, audio_path: Path) -> str:
        raise TranscriptionProviderError(f"Provider {self.provider_name} is not implemented")
