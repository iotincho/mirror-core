"""Durable local storage for raw voice notes and their metadata."""

import asyncio
import json
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from src.domain.audio_notes import AudioNote


class AudioNoteAlreadyExistsError(Exception):
    pass


class AudioNoteNotFoundError(Exception):
    pass


class AudioNoteStore(Protocol):
    async def create(self, note: AudioNote, content: bytes) -> None: ...

    async def get(self, note_id: UUID) -> AudioNote: ...

    async def save(self, note: AudioNote) -> None: ...

    def audio_path(self, note: AudioNote) -> Path: ...


class FileAudioNoteStore:
    """Keep audio bytes outside JSON metadata, with atomic metadata writes."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def create(self, note: AudioNote, content: bytes) -> None:
        return await asyncio.to_thread(self._create, note, content)

    async def get(self, note_id: UUID) -> AudioNote:
        return await asyncio.to_thread(self._get, note_id)

    async def save(self, note: AudioNote) -> None:
        return await asyncio.to_thread(self._save, note)

    def _create(self, note: AudioNote, content: bytes) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        metadata_path = self._metadata_path(note.id)
        audio_path = self.audio_path(note)
        if metadata_path.exists() or audio_path.exists():
            raise AudioNoteAlreadyExistsError(f"Audio note {note.id} already exists")
        temporary_audio = audio_path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary_audio.write_bytes(content)
            try:
                audio_path.hardlink_to(temporary_audio)
            except FileExistsError as error:
                raise AudioNoteAlreadyExistsError(f"Audio note {note.id} already exists") from error
        finally:
            temporary_audio.unlink(missing_ok=True)
        self._write_metadata(note, exists_ok=False)

    def _get(self, note_id: UUID) -> AudioNote:
        metadata_path = self._metadata_path(note_id)
        if not metadata_path.is_file():
            raise AudioNoteNotFoundError(f"Audio note {note_id} was not found")
        return AudioNote.model_validate_json(metadata_path.read_text(encoding="utf-8"))

    def _save(self, note: AudioNote) -> None:
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
        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(note.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if exists_ok:
                temporary.replace(destination)
            else:
                try:
                    destination.hardlink_to(temporary)
                except FileExistsError as error:
                    raise AudioNoteAlreadyExistsError(
                        f"Audio note {note.id} already exists"
                    ) from error
        finally:
            temporary.unlink(missing_ok=True)
