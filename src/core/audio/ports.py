"""Original audio and speech-to-text boundaries without paths or provider SDKs."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from src.core.domain.audio_notes import AudioNote


@dataclass(frozen=True)
class TranscriptionUpload:
    filename: str
    content: bytes = field(repr=False)


class TranscriptionSource(Protocol):
    async def prepare(self, *, timeout: float) -> TranscriptionUpload: ...


class AudioNoteStore(Protocol):
    async def create(self, note: AudioNote, content: bytes) -> None: ...
    async def get(self, note_id: UUID) -> AudioNote: ...
    async def save(self, note: AudioNote) -> None: ...
    async def restore_metadata(self, note: AudioNote) -> None: ...
    async def verify_original(self, note: AudioNote, *, size_bytes: int, sha256: str) -> None: ...
    async def original_sha256(self, note: AudioNote) -> str: ...
    def transcription_source(self, note: AudioNote) -> TranscriptionSource: ...


class TranscriptionProviderError(RuntimeError):
    """The provider could not produce a usable transcript."""


class TranscriptionProvider(Protocol):
    provider_name: str
    model_name: str

    async def transcribe(self, source: TranscriptionSource) -> str: ...
    async def close(self) -> None: ...


class UnavailableTranscriptionProvider:
    def __init__(self, provider_name: str, model_name: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name

    async def transcribe(self, source) -> str:
        raise TranscriptionProviderError(f"Provider {self.provider_name} is not implemented")

    async def close(self) -> None:
        """This unavailable adapter owns no connections."""
