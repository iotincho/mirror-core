"""Explicit, bounded experiment for links between two source documents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.config import get_settings
from src.constellation.contracts import LinkReport
from src.constellation.link_documents import LinkDocuments
from src.constellation.provider import OpenAILinkProvider
from src.dependencies import get_embedding_provider
from src.services.document_store import DocumentNotFoundError
from src.services.embedding_provider import EmbeddingProvider
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime

router = APIRouter(prefix="/documents", tags=["constellation"])


class LinkRequest(BaseModel):
    run_id: UUID
    persist: bool = False
    candidates_per_claim: int = Field(default=5, ge=1, le=10)
    max_claims: int = Field(default=20, ge=1, le=50)


@router.post("/{document_id}/links", response_model=LinkReport)
async def link_document(
    document_id: UUID,
    request: LinkRequest,
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> LinkReport:
    """Compare one completed run against evidence from other notes in this workspace."""
    try:
        run = runtime.extraction_store.get(document_id, request.run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Extraction run not found") from error
    if run.status != "completed":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Extraction run is not completed")
    settings = get_settings()
    try:
        document = runtime.document_store.get(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Document not found") from error
    provider = OpenAILinkProvider(
        settings.openai_api_key,
        settings.openai_reflection_model or settings.openai_model,
    )
    use_case = LinkDocuments(embeddings, runtime.graph_store, provider, runtime.graph_store)
    try:
        return use_case.execute(
            run,
            persist=request.persist,
            candidates_per_claim=request.candidates_per_claim,
            max_claims=request.max_claims,
            source_authored_at=document.authored_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Link comparison returned invalid data") from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Link comparison is unavailable") from error
