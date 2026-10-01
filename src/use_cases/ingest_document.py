"""Register original material before any interpretation is performed."""

from src.domain.documents import Document, NewDocument, build_document
from src.services.document_store import DocumentStore


class IngestDocument:
    """Create and persist one source document through the storage port."""

    def __init__(self, document_store: DocumentStore) -> None:
        self._document_store = document_store

    def execute(self, new_document: NewDocument) -> Document:
        document = build_document(new_document)
        self._document_store.save(document)
        return document

    def get(self, document_id: object) -> Document:
        """Retrieve already stored material for a retryable processing flow."""
        return self._document_store.get(document_id)
