"""Original document persistence and read-only graph presentation ports."""

from typing import Protocol

from src.domain.documents import Document
from src.graph.contracts import ExtractionGraph, LinkNeighborhood, LinkType


class GraphPersistenceError(RuntimeError):
    """Raised when document storage or graph navigation fails."""


class GraphStore(Protocol):
    async def persist_document(self, document: Document) -> None: ...

    async def delete_document(self, document_id: str) -> None: ...


class GraphBackend(GraphStore, Protocol):
    async def get_extraction_graph(
        self, document_id: str, *, layer: str | None = None, layers: list[str] | None = None
    ) -> ExtractionGraph: ...

    async def get_link_neighborhood(
        self,
        document_id: str,
        *,
        offset: int = 0,
        limit: int = 10,
        relation_type: LinkType | None = None,
    ) -> LinkNeighborhood: ...

    async def close(self) -> None: ...
