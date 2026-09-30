"""Models for an uploaded voice note and its transcription lifecycle."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

AudioNoteStatus = Literal["queued", "transcribing", "completed", "failed"]


class AudioNote(BaseModel):
    """Immutable audio identity plus the current transcription state."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    filename: str
    media_type: str
    size_bytes: int = Field(gt=0)
    storage_name: str
    created_at: datetime
    authored_at: datetime | None = None
    status: AudioNoteStatus
    transcript: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    error: str | None = None
    document_id: UUID | None = None
    document_error: str | None = None

    @field_validator("authored_at")
    @classmethod
    def authored_at_must_include_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("authored_at must include a timezone")
        return value


def new_audio_note(
    filename: str,
    media_type: str,
    size_bytes: int,
    authored_at: datetime | None,
) -> AudioNote:
    """Create metadata for raw audio that is about to be durably stored."""
    note_id = uuid4()
    suffix = Path(filename).suffix.lower()
    return AudioNote(
        id=note_id,
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        storage_name=f"{note_id}{suffix}",
        created_at=datetime.now(UTC),
        authored_at=authored_at,
        status="queued",
    )
