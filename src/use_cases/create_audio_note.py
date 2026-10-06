"""Validate and store original audio; transcription runs in the durable workflow."""

from datetime import datetime
from pathlib import Path

from src.domain.audio_notes import AudioNote, new_audio_note
from src.services.audio_note_store import AudioNoteStore

SUPPORTED_AUDIO_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class UnsupportedAudioFileError(ValueError):
    pass


class AudioFileTooLargeError(ValueError):
    pass


class CreateAudioNote:
    def __init__(self, store: AudioNoteStore, max_upload_bytes: int) -> None:
        self._store = store
        self._max_upload_bytes = max_upload_bytes

    async def execute(
        self,
        filename: str | None,
        media_type: str | None,
        content: bytes,
        authored_at: datetime | None,
    ) -> AudioNote:
        safe_filename, expected_type = validate_audio_upload(
            filename, media_type, content, self._max_upload_bytes
        )
        note = new_audio_note(safe_filename, expected_type, len(content), authored_at)
        await self._store.create(note, content)
        return note


def validate_audio_upload(
    filename: str | None, media_type: str | None, content: bytes, max_upload_bytes: int
) -> tuple[str, str]:
    if not filename:
        raise UnsupportedAudioFileError("An audio filename is required")
    safe_filename = Path(filename).name
    expected_type = SUPPORTED_AUDIO_TYPES.get(Path(safe_filename).suffix.lower())
    if expected_type is None:
        raise UnsupportedAudioFileError(
            "Unsupported audio type; use m4a, mp3, mp4, mpeg, mpga, wav, or webm"
        )
    if media_type and media_type not in {expected_type, "audio/x-m4a", "audio/x-wav"}:
        raise UnsupportedAudioFileError("Audio MIME type does not match its filename")
    if not content:
        raise UnsupportedAudioFileError("Audio files must not be empty")
    if len(content) > max_upload_bytes:
        raise AudioFileTooLargeError(f"Audio files must be at most {max_upload_bytes} bytes")
    return safe_filename, expected_type
