"""HTTP representations for uploaded voice notes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator

from src.adapters.access.api.public.schemas.journals import JournalReference
from src.core.domain.audio_notes import AudioNoteStatus
from src.core.domain.entry_triggers import EntryTrigger, InvitationTrigger


class AudioNoteResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime
    authored_at: datetime | None = None
    invitation_id: UUID | None = None
    invitation_question_id: UUID | None = None
    journal_reference: JournalReference | None = None
    entry_trigger: EntryTrigger | None = None
    status: AudioNoteStatus
    transcript: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    error: str | None = None
    document_id: UUID | None = None
    document_error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def project_entry_trigger(cls, value):
        if (
            isinstance(value, dict)
            and value.get("invitation_id")
            and value.get("entry_trigger") is None
        ):
            return {
                **value,
                "entry_trigger": InvitationTrigger(
                    kind="invitation",
                    invitation_id=value["invitation_id"],
                    question_id=value.get("invitation_question_id"),
                ),
            }
        return value
