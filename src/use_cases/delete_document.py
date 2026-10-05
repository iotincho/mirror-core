from uuid import UUID

from src.services.document_store import DocumentStore
from src.services.extraction_store import ExtractionStore
from src.services.graph_store import GraphStore


class DeleteDocument:
    def __init__(
        self,
        documents: DocumentStore,
        extractions: ExtractionStore,
        graph: GraphStore,
    ) -> None:
        self._documents = documents
        self._extractions = extractions
        self._graph = graph

    async def execute(self, document_id: UUID) -> None:
        await self._documents.get(document_id)
        await self._graph.delete_document(str(document_id))
        await self._extractions.delete_for_document(document_id)
        await self._documents.delete(document_id)
