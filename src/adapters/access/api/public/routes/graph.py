"""Read-only graph navigation retained for the PWA visualization."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.core.documents.ports import DocumentNotFoundError, DocumentStore
from src.core.graph.contracts import (
    EmotionCatalog,
    EmotionExploration,
    ExtractionGraph,
    LinkNeighborhood,
    LinkType,
)
from src.core.graph.ports import EmotionNotFoundError, GraphBackend, GraphPersistenceError
from src.use_cases.graph.read_graph import ReadGraph


def build_router(get_document_store, get_graph_store):
    router = APIRouter(tags=["graph"])

    @router.get("/documents/{document_id}/links", response_model=LinkNeighborhood)
    async def neighborhood(
        document_id: UUID,
        documents: Annotated[DocumentStore, Depends(get_document_store)],
        graph: Annotated[GraphBackend, Depends(get_graph_store)],
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=1, le=40),
        relation_type: LinkType | None = None,
    ):
        try:
            return await ReadGraph(graph, documents).neighborhood(
                document_id,
                offset=offset,
                limit=limit,
                relation_type=relation_type,
            )
        except DocumentNotFoundError as error:
            raise HTTPException(404, "Document not found") from error
        except GraphPersistenceError as error:
            raise HTTPException(502, "Graph navigation is unavailable") from error

    @router.get("/documents/{document_id}/graph", response_model=ExtractionGraph)
    async def extraction_graph(
        document_id: UUID,
        documents: Annotated[DocumentStore, Depends(get_document_store)],
        graph: Annotated[GraphBackend, Depends(get_graph_store)],
        layer: str | None = Query(default=None, min_length=1, max_length=80),
    ):
        try:
            return await ReadGraph(graph, documents).extraction_graph(document_id, layer=layer)
        except DocumentNotFoundError as error:
            raise HTTPException(404, "Document not found") from error
        except GraphPersistenceError as error:
            raise HTTPException(502, "Graph navigation is unavailable") from error

    @router.get("/graph/emotions", response_model=EmotionCatalog)
    async def emotion_catalog(
        graph: Annotated[GraphBackend, Depends(get_graph_store)],
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        try:
            return await ReadGraph(graph).emotion_catalog(offset=offset, limit=limit)
        except GraphPersistenceError as error:
            raise HTTPException(502, "Emotion catalog is unavailable") from error

    @router.get("/graph/emotions/explore", response_model=EmotionExploration)
    async def emotion_exploration(
        graph: Annotated[GraphBackend, Depends(get_graph_store)],
        emotion: str = Query(min_length=1, max_length=240),
        depth: int = Query(default=1, ge=1, le=3),
        limit: int = Query(default=100, ge=2, le=500),
    ):
        if not emotion.strip():
            raise HTTPException(422, "Emotion must not be blank")
        try:
            return await ReadGraph(graph).emotion_exploration(emotion, depth=depth, limit=limit)
        except EmotionNotFoundError as error:
            raise HTTPException(404, "Emotion not found") from error
        except GraphPersistenceError as error:
            raise HTTPException(502, "Emotion exploration is unavailable") from error

    @router.get("/documents/{document_id}/emotions/graph", response_model=EmotionExploration)
    async def document_emotion_neighborhood(
        document_id: UUID,
        documents: Annotated[DocumentStore, Depends(get_document_store)],
        graph: Annotated[GraphBackend, Depends(get_graph_store)],
        limit: int = Query(default=100, ge=2, le=500),
    ):
        try:
            return await ReadGraph(graph, documents).document_emotions(document_id, limit=limit)
        except DocumentNotFoundError as error:
            raise HTTPException(404, "Document not found") from error
        except GraphPersistenceError as error:
            raise HTTPException(502, "Document emotions are unavailable") from error

    return router
