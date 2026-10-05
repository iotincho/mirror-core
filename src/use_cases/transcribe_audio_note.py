"""Create, transcribe, and persist voice notes as searchable Documents."""

import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from src.domain.audio_notes import AudioNote, new_audio_note
from src.domain.documents import NewDocument
from src.services.audio_note_store import AudioNoteStore
from src.services.document_store import DocumentAlreadyExistsError
from src.services.transcription_provider import TranscriptionProvider
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument

logger = logging.getLogger(__name__)

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


class TranscribeAudioNote:
    def __init__(
        self,
        store: AudioNoteStore,
        provider: TranscriptionProvider,
        document_processor: IngestAndExtractDocument,
    ) -> None:
        self._store = store
        self._provider = provider
        self._document_processor = document_processor

    async def execute(self, note_id: UUID) -> AudioNote:
        note = await self._store.get(note_id)
        if note.status == "completed" and note.document_id is not None:
            return note
        if note.status == "completed" and note.transcript is not None:
            return await self._persist_transcript(note)
        transcribing = note.model_copy(update={"status": "transcribing", "error": None})
        await self._store.save(transcribing)
        try:
            transcript = await self._provider.transcribe(self._store.audio_path(transcribing))
        except Exception:
            logger.exception("audio_transcription_failed audio_note_id=%s", note_id)
            failed = transcribing.model_copy(
                update={"status": "failed", "error": "transcription_failed"}
            )
            await self._store.save(failed)
            return failed
        completed = transcribing.model_copy(
            update={
                "status": "completed",
                "transcript": transcript,
                "transcription_provider": self._provider.provider_name,
                "transcription_model": self._provider.model_name,
            }
        )
        await self._store.save(completed)
        return await self._persist_transcript(completed)

    async def _persist_transcript(self, note: AudioNote) -> AudioNote:
        assert note.transcript is not None
        try:
            new_document = NewDocument(
                id=note.id,
                content=note.transcript,
                source="pwa_audio",
                metadata={
                    "audio_note_id": str(note.id),
                    "filename": note.filename,
                    "media_type": note.media_type,
                    "transcription_provider": note.transcription_provider or "unknown",
                    "transcription_model": note.transcription_model or "unknown",
                },
                authored_at=note.authored_at,
            )
            processed = await self._document_processor.execute(new_document)
        except DocumentAlreadyExistsError:
            try:
                processed = await self._document_processor.process_existing(note.id)
            except Exception:
                return await self._document_processing_failed(note)
        except Exception:
            return await self._document_processing_failed(note)

        completed = note.model_copy(
            update={"document_id": processed.document.id, "document_error": None}
        )
        await self._store.save(completed)
        logger.info("audio_transcription_completed audio_note_id=%s", note.id)
        return completed

    async def _document_processing_failed(self, note: AudioNote) -> AudioNote:
        logger.exception("audio_document_persistence_failed audio_note_id=%s", note.id)
        failed_document = note.model_copy(
            update={"document_error": "document_processing_failed"}
        )
        await self._store.save(failed_document)
        return failed_document


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
