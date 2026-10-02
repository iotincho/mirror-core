"""Explicit, bounded experiment for links between two source documents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config import get_settings
from src.constellation.contracts import ExtractionSummary, LinkNeighborhood, LinkReport, LinkType
from src.constellation.link_documents import LinkDocuments
from src.constellation.provider import OpenAILinkProvider
from src.dependencies import get_embedding_provider
from src.embeddings.contracts import EmbeddingSpec
from src.services.document_store import DocumentNotFoundError
from src.services.embedding_provider import EmbeddingProvider
from src.services.graph_store import GraphPersistenceError
from src.use_cases.embed_claims import ClaimEmbeddingFailedError, EmbedClaims
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime

router = APIRouter(prefix="/documents", tags=["constellation"])


class LinkRequest(BaseModel):
    run_id: UUID
    persist: bool = False
    candidates_per_claim: int = Field(default=5, ge=1, le=10)
    max_claims: int = Field(default=20, ge=1, le=50)


@router.get("/{document_id}/links", response_model=LinkNeighborhood)
def read_links(
    document_id: UUID,
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    relation_type: LinkType | None = None,
) -> LinkNeighborhood:
    try:
        runtime.document_store.get(document_id)
        return runtime.graph_store.get_link_neighborhood(
            str(document_id), offset=offset, limit=limit, relation_type=relation_type,
        )
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except GraphPersistenceError as error:
        raise HTTPException(status_code=503, detail="Connections are unavailable") from error


@router.get("/{document_id}/extractions", response_model=list[ExtractionSummary])
def read_extractions(
    document_id: UUID,
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> list[ExtractionSummary]:
    try:
        runtime.document_store.get(document_id)
        runs = runtime.extraction_store.list_for_document(document_id)
        settings = get_settings()
        ready = runtime.graph_store.ready_extraction_ids(
            {str(run.id): len(run.result.claims) for run in runs
             if run.status == "completed" and run.result is not None},
            EmbeddingSpec(provider=settings.embedding_provider,
                          model=settings.openai_embedding_model,
                          dimensions=settings.openai_embedding_dimensions),
        )
        return [ExtractionSummary(
            id=run.id, profile_name=run.profile_name, status=run.status,
            created_at=run.created_at, claim_count=len(run.result.claims) if run.result else 0,
            ready=str(run.id) in ready,
            origin=run.origin,
            graph_persisted=(runtime.graph_store.supplemental_items_persisted(run)
                             if run.origin == "constellation" else str(run.id) in ready),
        ) for run in runs]
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except (GraphPersistenceError, ValueError, OSError) as error:
        raise HTTPException(status_code=503, detail="Extraction history is unavailable") from error


@router.post("/{document_id}/links", response_model=LinkReport)
def link_document(
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
    use_case = LinkDocuments(
        embeddings, runtime.graph_store, provider, runtime.graph_store, runtime.extraction_store,
        model_name=settings.openai_reflection_model or settings.openai_model or "unconfigured",
    )
    try:
        return use_case.execute(
            run,
            document,
            persist=request.persist,
            candidates_per_claim=request.candidates_per_claim,
            max_claims=request.max_claims,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Link comparison returned invalid data") from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Link comparison is unavailable") from error


@router.post("/{document_id}/extractions/{run_id}/embeddings")
def retry_supplement_embeddings(
    document_id: UUID, run_id: UUID,
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> dict[str, str | int]:
    """Retry vectors for a saved supplement, without calling the analysis model."""
    try:
        document = runtime.document_store.get(document_id)
        run = runtime.extraction_store.get(document_id, run_id)
        if run.origin != "constellation" or run.status != "completed":
            raise HTTPException(status_code=422, detail="A completed supplement is required")
        if not runtime.graph_store.supplemental_items_persisted(run):
            raise HTTPException(status_code=409, detail="Supplement is not persisted in the graph")
        count = EmbedClaims(embeddings, runtime.graph_store).execute(document, run)
        return {"run_id": str(run.id), "embeddings_status": "ready", "claim_count": count}
    except (DocumentNotFoundError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail="Supplement not found") from error
    except (GraphPersistenceError, ClaimEmbeddingFailedError) as error:
        raise HTTPException(
            status_code=503, detail="Supplement embeddings are unavailable"
        ) from error
