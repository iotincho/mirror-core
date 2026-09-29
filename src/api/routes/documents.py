"""Document-ingestion HTTP endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from src.api.schemas.documents import (
    CreateDocumentRequest,
    DocumentResponse,
    ProcessedDocumentResponse,
)
from src.dependencies import (
    get_delete_document,
    get_ingest_and_extract_document,
    get_ingest_document_file,
    get_list_documents,
)
from src.domain.documents import NewDocument
from src.services.document_store import DocumentAlreadyExistsError, DocumentNotFoundError
from src.use_cases.delete_document import DeleteDocument
from src.use_cases.embed_claims import ClaimEmbeddingFailedError
from src.use_cases.embed_documents import DocumentEmbeddingFailedError
from src.use_cases.extract_and_persist_document import GraphPersistenceFailedError
from src.use_cases.extract_document import ExtractionRunFailedError
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document_file import (
    IngestDocumentFile,
    InvalidDocumentEncodingError,
    UnsupportedDocumentFileError,
)
from src.use_cases.list_documents import ListDocuments

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    use_case: Annotated[ListDocuments, Depends(get_list_documents)],
) -> list[DocumentResponse]:
    return [DocumentResponse(**document.model_dump()) for document in use_case.execute()]


@router.post("", response_model=ProcessedDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    request: CreateDocumentRequest,
    use_case: Annotated[IngestAndExtractDocument, Depends(get_ingest_and_extract_document)],
) -> ProcessedDocumentResponse:
    """Store and immediately extract knowledge from source material."""
    try:
        processed = use_case.execute(NewDocument(**request.model_dump()))
    except DocumentAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ExtractionRunFailedError as error:
        raise _extraction_failed_response(error) from error
    except GraphPersistenceFailedError as error:
        raise _graph_persistence_failed_response(error) from error
    except (ClaimEmbeddingFailedError, DocumentEmbeddingFailedError) as error:
        raise _embedding_failed_response(error) from error

    return ProcessedDocumentResponse(
        document=DocumentResponse(**processed.document.model_dump()),
        extraction=processed.extraction,
    )


@router.post(
    "/files",
    response_model=ProcessedDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_from_file(
    file: Annotated[UploadFile, File(description="UTF-8 Markdown or plain-text note")],
    file_use_case: Annotated[IngestDocumentFile, Depends(get_ingest_document_file)],
    use_case: Annotated[IngestAndExtractDocument, Depends(get_ingest_and_extract_document)],
    document_id: Annotated[UUID | None, Form()] = None,
    authored_at: Annotated[datetime | None, Form()] = None,
) -> ProcessedDocumentResponse:
    """Store and immediately extract from an uploaded `.md` or `.txt` note."""
    try:
        new_document = file_use_case.build_new_document(
            file.filename, await file.read(), document_id, authored_at
        )
    except UnsupportedDocumentFileError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except InvalidDocumentEncodingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error.errors(),
        ) from error

    try:
        processed = use_case.execute(new_document)
    except DocumentAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ExtractionRunFailedError as error:
        raise _extraction_failed_response(error) from error
    except GraphPersistenceFailedError as error:
        raise _graph_persistence_failed_response(error) from error
    except (ClaimEmbeddingFailedError, DocumentEmbeddingFailedError) as error:
        raise _embedding_failed_response(error) from error

    return ProcessedDocumentResponse(
        document=DocumentResponse(**processed.document.model_dump()),
        extraction=processed.extraction,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    use_case: Annotated[DeleteDocument, Depends(get_delete_document)],
) -> None:
    try:
        use_case.execute(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _extraction_failed_response(error: ExtractionRunFailedError) -> HTTPException:
    """Tell callers the document was stored but did not finish processing."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"message": "Extraction failed", "run_id": str(error.run_id)},
    )


def _graph_persistence_failed_response(error: GraphPersistenceFailedError) -> HTTPException:
    """Tell callers the source and extraction exist but are not queryable in the graph yet."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "message": "Document was extracted but graph persistence failed",
            "run_id": str(error.run_id),
        },
    )


def _embedding_failed_response(
    error: ClaimEmbeddingFailedError | DocumentEmbeddingFailedError,
) -> HTTPException:
    """Tell callers the persisted material is not yet semantically searchable."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "message": "Document was extracted but embeddings failed",
            "run_id": (
                error.run_id
                if isinstance(error, ClaimEmbeddingFailedError)
                else error.document_id
            ),
        },
    )
