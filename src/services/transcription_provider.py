"""Compatibility imports for speech-to-text ports and safe errors."""

from src.core.audio.ports import TranscriptionProvider as TranscriptionProvider
from src.core.audio.ports import TranscriptionProviderError as TranscriptionProviderError
from src.core.audio.ports import (
    UnavailableTranscriptionProvider as UnavailableTranscriptionProvider,
)
