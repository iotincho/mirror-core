"""Public projections omit workflow configuration, leases and credentials."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.api.schemas.audio_notes import AudioNoteResponse
from src.api.schemas.documents import DocumentResponse
from src.processing.projections import processing_projection


class ProcessingError(BaseModel):
    code: str
    message: str
    retryable: bool


class ProcessingResponse(BaseModel):
    id: UUID
    workflow: str
    workflow_version: int
    resource_kind: str
    resource_id: UUID
    document_id: UUID | None
    extraction_run_id: UUID | None
    parent_processing_id: UUID | None
    child_processing_id: UUID | None
    status: str
    stage: str
    version: int
    stage_attempt: int
    error: ProcessingError | None
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_record(cls, record):
        return cls.model_validate(processing_projection(record))


class AcceptedDocument(BaseModel):
    document: DocumentResponse
    processing: ProcessingResponse


class AcceptedAudio(BaseModel):
    audio_note: AudioNoteResponse
    processing: ProcessingResponse


class DocumentSnapshot(DocumentResponse):
    processing: ProcessingResponse | None = None


class AudioSnapshot(AudioNoteResponse):
    processing: ProcessingResponse | None = None


class ProcessingPage(BaseModel):
    items: list[ProcessingResponse]
    next_cursor: UUID | None
