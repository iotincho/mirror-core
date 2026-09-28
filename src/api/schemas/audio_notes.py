"""HTTP representations for uploaded voice notes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.domain.audio_notes import AudioNoteStatus


class AudioNoteResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime
    authored_at: datetime | None = None
    status: AudioNoteStatus
    transcript: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    error: str | None = None
