"""HTTP contracts for document ingestion."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator

from src.adapters.access.api.public.schemas.journals import JournalReference
from src.core.domain.documents import NewDocument
from src.core.domain.entry_triggers import EntryTrigger, EntryTriggerInput, read_document_trigger


class CreateDocumentRequest(NewDocument):
    """Typed invitation input; provenance is stored separately from user content."""

    invitation_id: UUID | None = None
    invitation_question_id: UUID | None = None
    journal_reference: JournalReference | None = None
    entry_trigger: EntryTriggerInput | None = None


class DocumentResponse(BaseModel):
    id: UUID
    title: str | None = None
    content: str
    source: str
    metadata: dict[str, str]
    created_at: datetime
    authored_at: datetime | None = None
    entry_trigger: EntryTrigger | None = None

    @model_validator(mode="before")
    @classmethod
    def project_entry_trigger(cls, value):
        if isinstance(value, dict) and "entry_trigger" not in value:
            return {**value, "entry_trigger": read_document_trigger(value.get("metadata") or {})}
        return value
