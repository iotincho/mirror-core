"""Port for persisting validated extractions in a knowledge graph."""

from typing import Protocol

from src.domain.documents import Document
from src.services.claim_embedding_store import ClaimEmbeddingStore
from src.services.document_embedding_store import DocumentEmbeddingStore
from src.services.extraction_store import ExtractionRun
from src.services.reflection_context_store import ReflectionContextStore


class GraphPersistenceError(RuntimeError):
    """Raised when a completed extraction cannot be stored in the graph."""


class GraphStore(Protocol):
    """Infrastructure boundary shared by application use cases and delivery adapters."""

    async def persist(self, document: Document, extraction: ExtractionRun) -> None:
        """Write one completed, evidence-backed extraction atomically."""

    async def delete_document(self, document_id: str) -> None:
        """Delete a document and all graph records owned by it."""


class GraphBackend(
    GraphStore,
    ClaimEmbeddingStore,
    DocumentEmbeddingStore,
    ReflectionContextStore,
    Protocol,
):
    """Complete graph capability set supplied by the configured database adapter."""

    async def close(self) -> None:
        """Release connections held by the adapter."""
