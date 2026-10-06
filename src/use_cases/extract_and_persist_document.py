"""Compose extraction and graph persistence without coupling either adapter to HTTP."""

import logging
from uuid import UUID

from src.services.extraction_store import ExtractionRun
from src.services.graph_store import GraphPersistenceError, GraphStore
from src.use_cases.extract_document import ExtractDocument

logger = logging.getLogger(__name__)


class GraphPersistenceFailedError(RuntimeError):
    """Signals that an extraction was saved locally but not in the graph store."""

    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        super().__init__(f"Extraction run {run_id} could not be persisted in the graph store")


class ExtractAndPersistDocument:
    """Run extraction, then make its validated result available to graph queries."""

    def __init__(self, extract_document: ExtractDocument, graph_store: GraphStore) -> None:
        self._extract_document = extract_document
        self._graph_store = graph_store

    async def execute(self, document_id: UUID, profile_name: str = "v4") -> ExtractionRun:
        extraction = await self._extract_document.execute(document_id, profile_name)
        document = await self._extract_document.get_document(document_id)
        try:
            await self._graph_store.persist(document, extraction)
        except GraphPersistenceError as error:
            logger.exception(
                "graph_persistence_failed document_id=%s run_id=%s error_type=%s",
                document_id,
                extraction.id,
                type(error).__name__,
            )
            raise GraphPersistenceFailedError(extraction.id) from error
        return extraction

    async def get_document(self, document_id: UUID):
        """Expose preserved input to the embedding composition use case."""
        return await self._extract_document.get_document(document_id)
