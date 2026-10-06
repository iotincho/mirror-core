"""Turn an uploaded UTF-8 text file into an original Document."""

from datetime import datetime
from pathlib import Path
from uuid import UUID

from src.domain.documents import Document, NewDocument
from src.services.document_store import DocumentStore
from src.use_cases.ingest_document import IngestDocument

SUPPORTED_TEXT_EXTENSIONS = {".md", ".txt"}


class UnsupportedDocumentFileError(ValueError):
    """Raised when an uploaded file is not a supported text-note format."""


class InvalidDocumentEncodingError(ValueError):
    """Raised when a supported file cannot be decoded as UTF-8."""


class IngestDocumentFile:
    """Register an uploaded Markdown or plain-text file through the normal document flow."""

    def __init__(self, document_store: DocumentStore) -> None:
        self._ingest_document = IngestDocument(document_store)

    def build_new_document(
        self,
        filename: str | None,
        content: bytes,
        document_id: UUID | None = None,
        authored_at: datetime | None = None,
    ) -> NewDocument:
        """Validate an upload and translate it into the provider-neutral input model."""
        if not filename:
            raise UnsupportedDocumentFileError("A filename is required")

        safe_filename = Path(filename).name
        extension = Path(safe_filename).suffix.lower()
        if extension not in SUPPORTED_TEXT_EXTENSIONS:
            supported_formats = ", ".join(sorted(SUPPORTED_TEXT_EXTENSIONS))
            raise UnsupportedDocumentFileError(
                f"Unsupported file type {extension or '(none)'}; use {supported_formats}"
            )

        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidDocumentEncodingError("Document files must use UTF-8 encoding") from error

        return NewDocument(
            content=text_content,
            source="file_upload",
            metadata={"filename": safe_filename, "format": extension.removeprefix(".")},
            id=document_id,
            authored_at=authored_at,
        )

    async def execute(self, filename: str | None, content: bytes) -> Document:
        """Persist a file directly for callers that intentionally skip extraction."""
        return await self._ingest_document.execute(self.build_new_document(filename, content))
