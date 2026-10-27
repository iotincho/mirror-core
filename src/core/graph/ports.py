"""Original document persistence and read-only graph presentation ports."""

from typing import Protocol

from src.core.documents.ports import DocumentProjection
from src.core.documents.ports import GraphPersistenceError as GraphPersistenceError
from src.core.graph.contracts import (
    EmotionCatalog,
    EmotionExploration,
    ExtractionGraph,
    LinkNeighborhood,
    LinkType,
)


class EmotionNotFoundError(LookupError):
    """The requested emotion label has no reported occurrences in this workspace."""


class GraphStore(DocumentProjection, Protocol):
    async def delete_document(self, document_id: str) -> None: ...


class GraphBackend(GraphStore, Protocol):
    async def list_emotions(self, *, offset: int = 0, limit: int = 100) -> EmotionCatalog: ...

    async def explore_emotion(
        self, emotion: str, *, depth: int = 1, limit: int = 100
    ) -> EmotionExploration: ...

    async def explore_document_emotions(
        self, document_id: str, *, limit: int = 100
    ) -> EmotionExploration: ...

    async def get_extraction_graph(
        self, document_id: str, *, layer: str | None = None
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
