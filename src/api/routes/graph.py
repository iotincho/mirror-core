"""Read-only graph navigation retained for the PWA visualization."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.dependencies import get_document_store, get_graph_store
from src.graph.contracts import (
    EmotionCatalog,
    EmotionExploration,
    ExtractionGraph,
    LinkNeighborhood,
    LinkType,
)
from src.services.document_store import DocumentNotFoundError, DocumentStore
from src.services.graph_store import EmotionNotFoundError, GraphBackend, GraphPersistenceError

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
        await documents.get(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(404, "Document not found") from error
    try:
        return await graph.get_link_neighborhood(
            str(document_id),
            offset=offset,
            limit=limit,
            relation_type=relation_type,
        )
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
        document = await documents.get(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(404, "Document not found") from error
    try:
        result = await graph.get_extraction_graph(str(document_id), layer=layer)
    except GraphPersistenceError as error:
        raise HTTPException(502, "Graph navigation is unavailable") from error
    label = document.title or document.metadata.get("title") or document.metadata.get("filename")
    label = (
        label
        or next((line.strip() for line in document.content.splitlines() if line.strip()), "Nota")[
            :80
        ]
    )
    return result.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"label": label}) if node.id == result.root_id else node
                for node in result.nodes
            ]
        }
    )


@router.get("/graph/emotions", response_model=EmotionCatalog)
async def emotion_catalog(
    graph: Annotated[GraphBackend, Depends(get_graph_store)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
):
    try:
        return await graph.list_emotions(offset=offset, limit=limit)
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
        return await graph.explore_emotion(emotion, depth=depth, limit=limit)
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
        await documents.get(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(404, "Document not found") from error
    try:
        return await graph.explore_document_emotions(str(document_id), limit=limit)
    except GraphPersistenceError as error:
        raise HTTPException(502, "Document emotions are unavailable") from error
