"""Routes that trigger experimental, evidence-backed extraction runs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.schemas.extractions import CreateExtractionRequest
from src.dependencies import get_extract_persist_and_embed_document
from src.extraction.profiles import UnknownExtractionProfileError
from src.services.document_store import DocumentNotFoundError
from src.services.extraction_store import ExtractionRun
from src.use_cases.embed_claims import ClaimEmbeddingFailedError
from src.use_cases.embed_documents import DocumentEmbeddingFailedError
from src.use_cases.extract_and_persist_document import (
    GraphPersistenceFailedError,
)
from src.use_cases.extract_document import ExtractionRunFailedError
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument

router = APIRouter(prefix="/documents", tags=["extractions"])


@router.post(
    "/{document_id}/extractions",
    response_model=ExtractionRun,
    status_code=status.HTTP_201_CREATED,
)
async def create_extraction(
    document_id: UUID,
    request: CreateExtractionRequest,
    use_case: Annotated[
        ExtractPersistAndEmbedDocument,
        Depends(get_extract_persist_and_embed_document),
    ],
) -> ExtractionRun:
    """Run a selected profile and persist its validated result in the graph store."""
    try:
        return await use_case.execute(document_id, request.profile)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except UnknownExtractionProfileError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ExtractionRunFailedError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Extraction failed", "run_id": str(error.run_id)},
        ) from error
    except GraphPersistenceFailedError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Extraction completed but graph persistence failed",
                "run_id": str(error.run_id),
            },
        ) from error
    except (ClaimEmbeddingFailedError, DocumentEmbeddingFailedError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Extraction was persisted but embeddings failed",
                "run_id": (
                error.run_id
                if isinstance(error, ClaimEmbeddingFailedError)
                else error.document_id
            ),
            },
        ) from error
