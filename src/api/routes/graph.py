"""Read-only graph navigation retained for the PWA visualization."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.dependencies import get_document_store, get_graph_store
from src.graph.contracts import LinkNeighborhood, LinkType
from src.services.document_store import DocumentNotFoundError, DocumentStore
from src.services.graph_store import GraphBackend, GraphPersistenceError

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
