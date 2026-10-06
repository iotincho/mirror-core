"""Generate and persist a versioned vector for an original document."""

import hashlib

from src.domain.documents import Document
from src.embeddings.contracts import DocumentEmbeddingRecord
from src.services.document_embedding_store import (
    DocumentEmbeddingStore,
    DocumentEmbeddingStoreError,
)
from src.services.embedding_provider import EmbeddingProvider, EmbeddingProviderError


class DocumentEmbeddingFailedError(RuntimeError):
    """Signals that a persisted document could not receive its semantic vector."""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"Document {document_id} could not be embedded")


class EmbedDocument:
    """Embed preserved source text so whole notes can be found semantically."""

    def __init__(self, provider: EmbeddingProvider, store: DocumentEmbeddingStore) -> None:
        self._provider = provider
        self._store = store

    async def execute(self, document: Document) -> None:
        try:
            vectors = await self._provider.embed([document.content])
            if len(vectors) != 1:
                raise EmbeddingProviderError("Provider returned an unexpected number of embeddings")
            vector = vectors[0]
            if len(vector.vector) != vector.spec.dimensions:
                raise EmbeddingProviderError("Provider returned an invalid embedding dimension")
            text_hash = hashlib.sha256(document.content.encode()).hexdigest()
            await self._store.persist_document_embedding(
                DocumentEmbeddingRecord(
                    id=f"{document.id}:embedding:{vector.spec.index_suffix}:{text_hash[:16]}",
                    document_id=str(document.id),
                    text_hash=text_hash,
                    content=document.content,
                    source=document.source,
                    metadata=document.metadata,
                    created_at=document.created_at,
                    authored_at=document.authored_at,
                    vector=vector.vector,
                    spec=vector.spec,
                ),
                vector.spec,
            )
        except (EmbeddingProviderError, DocumentEmbeddingStoreError) as error:
            raise DocumentEmbeddingFailedError(str(document.id)) from error
