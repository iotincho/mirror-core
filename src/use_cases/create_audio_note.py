"""Validate and store original audio; transcription runs in the durable workflow."""

from datetime import datetime

from src.core.audio.uploads import (
    SUPPORTED_AUDIO_TYPES as SUPPORTED_AUDIO_TYPES,
)
from src.core.audio.uploads import (
    AudioFileTooLargeError as AudioFileTooLargeError,
)
from src.core.audio.uploads import (
    UnsupportedAudioFileError as UnsupportedAudioFileError,
)
from src.core.audio.uploads import (
    validate_audio_upload as validate_audio_upload,
)
from src.domain.audio_notes import AudioNote, new_audio_note
from src.services.audio_note_store import AudioNoteStore


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
