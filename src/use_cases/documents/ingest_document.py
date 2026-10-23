"""Register original material before any interpretation is performed."""

from src.core.documents.ports import DocumentStore
from src.core.domain.documents import Document, NewDocument, build_document


class IngestDocument:
    """Create and persist one source document through the storage port."""

    def __init__(self, document_store: DocumentStore) -> None:
        self._document_store = document_store

    async def execute(self, new_document: NewDocument) -> Document:
        document = build_document(new_document)
        await self._document_store.save(document)
        return document

    async def get(self, document_id: object) -> Document:
        """Retrieve already stored material for a retryable processing flow."""
        return await self._document_store.get(document_id)
