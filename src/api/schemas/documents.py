"""HTTP contracts for document ingestion."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.domain.documents import NewDocument


class CreateDocumentRequest(NewDocument):
    """HTTP alias for the application input contract."""


class DocumentResponse(BaseModel):
    id: UUID
    title: str | None = None
    content: str
    source: str
    metadata: dict[str, str]
    created_at: datetime
    authored_at: datetime | None = None
