"""Read and delete originals; uploads use the durable /v2 routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.schemas.documents import DocumentResponse
from src.dependencies import get_delete_document, get_list_documents
from src.services.document_store import DocumentNotFoundError
from src.use_cases.delete_document import DeleteDocument
from src.use_cases.list_documents import ListDocuments

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    use_case: Annotated[ListDocuments, Depends(get_list_documents)],
) -> list[DocumentResponse]:
    return [DocumentResponse(**document.model_dump()) for document in await use_case.execute()]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    use_case: Annotated[DeleteDocument, Depends(get_delete_document)],
) -> None:
    try:
        await use_case.execute(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
