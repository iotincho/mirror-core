"""Durable local storage for raw voice notes and their metadata."""

import json
from pathlib import Path
from typing import Protocol
from uuid import UUID

from src.domain.audio_notes import AudioNote


class AudioNoteAlreadyExistsError(Exception):
    pass


class AudioNoteNotFoundError(Exception):
    pass


class AudioNoteStore(Protocol):
    def create(self, note: AudioNote, content: bytes) -> None: ...

    def get(self, note_id: UUID) -> AudioNote: ...

    def save(self, note: AudioNote) -> None: ...

    def audio_path(self, note: AudioNote) -> Path: ...


class FileAudioNoteStore:
    """Keep audio bytes outside JSON metadata, with atomic metadata writes."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def create(self, note: AudioNote, content: bytes) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        metadata_path = self._metadata_path(note.id)
        audio_path = self.audio_path(note)
        if metadata_path.exists() or audio_path.exists():
            raise AudioNoteAlreadyExistsError(f"Audio note {note.id} already exists")
        temporary_audio = audio_path.with_suffix(f"{audio_path.suffix}.tmp")
        temporary_audio.write_bytes(content)
        temporary_audio.replace(audio_path)
        self._write_metadata(note, exists_ok=False)

    def get(self, note_id: UUID) -> AudioNote:
        metadata_path = self._metadata_path(note_id)
        if not metadata_path.is_file():
            raise AudioNoteNotFoundError(f"Audio note {note_id} was not found")
        return AudioNote.model_validate_json(metadata_path.read_text(encoding="utf-8"))

    def save(self, note: AudioNote) -> None:
        if not self._metadata_path(note.id).is_file():
            raise AudioNoteNotFoundError(f"Audio note {note.id} was not found")
        self._write_metadata(note, exists_ok=True)

    def audio_path(self, note: AudioNote) -> Path:
        return self._directory / note.storage_name

    def _metadata_path(self, note_id: UUID) -> Path:
        return self._directory / f"{note_id}.json"

    def _write_metadata(self, note: AudioNote, exists_ok: bool) -> None:
        destination = self._metadata_path(note.id)
        if not exists_ok and destination.exists():
            raise AudioNoteAlreadyExistsError(f"Audio note {note.id} already exists")
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(note.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
