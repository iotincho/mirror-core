"""Versioned deferred ingestion; legacy clients migrate in the next stage."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import ValidationError

from src.adapters.access.api.public.errors import invitation_status
from src.adapters.access.api.public.schemas.documents import CreateDocumentRequest, DocumentResponse
from src.adapters.access.api.public.schemas.processing import (
    AcceptedAudio,
    AcceptedDocument,
    AudioSnapshot,
    DocumentSnapshot,
    ProcessingPage,
    ProcessingResponse,
    ReprocessDocumentsRequest,
    ReprocessDocumentsResponse,
)
from src.core.audio.errors import AudioNoteNotFoundError
from src.core.audio.uploads import AudioFileTooLargeError, UnsupportedAudioFileError
from src.core.documents.ports import DocumentNotFoundError
from src.core.domain.documents import NewDocument
from src.core.exteriorization.models import InvitationError
from src.core.graph.ports import GraphPersistenceError
from src.core.processing.errors import StorageUnavailable
from src.core.processing.reads import ProcessingNotFound
from src.core.processing.submissions import SubmissionConflict
from src.use_cases.documents.ingest_document_file import (
    InvalidDocumentEncodingError,
    UnsupportedDocumentFileError,
)

Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def http_error(error):
    if isinstance(error, InvitationError):
        return HTTPException(invitation_status(error.code), error.code)
    if isinstance(error, ProcessingNotFound):
        return HTTPException(404, "Processing not found")
    if isinstance(error, (DocumentNotFoundError, AudioNoteNotFoundError)):
        return HTTPException(404, "Resource not found")
    if isinstance(error, ValueError) and str(error) == "processing_active":
        return HTTPException(409, "processing_active")
    if isinstance(error, SubmissionConflict):
        return HTTPException(409, str(error))
    if isinstance(error, (UnsupportedAudioFileError, UnsupportedDocumentFileError)):
        return HTTPException(415, str(error))
    if isinstance(error, AudioFileTooLargeError):
        return HTTPException(413, str(error))
    if isinstance(
        error,
        (ValidationError, InvalidDocumentEncodingError, ValueError),
    ):
        return HTTPException(422, "Invalid upload or processing request")
    if isinstance(error, StorageUnavailable):
        return HTTPException(
            503, "Processing storage unavailable; retry with the same Idempotency-Key"
        )
    if isinstance(error, GraphPersistenceError):
        return HTTPException(
            503, "Document graph storage unavailable; retry with the same Idempotency-Key"
        )
    raise error


def accepted_headers(request, response, record):
    response.status_code = 200 if record.status == "completed" else 202
    root = request.scope.get("root_path", "").rstrip("/")
    response.headers["Location"] = f"{root}/processing/{record.id}"


async def read_upload(file, limit):
    chunks, size = [], 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "Upload exceeds configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def build_router(get_actions, get_limits):
    router = APIRouter(tags=["processing"])

    @router.post("/v2/documents", response_model=AcceptedDocument, status_code=202)
    async def submit_document(
        payload: CreateDocumentRequest,
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
        limits=Depends(get_limits),
    ):
        if len(payload.content.encode()) > limits.document_max_upload_bytes:
            raise HTTPException(413, "Upload exceeds configured size limit")
        try:
            document, record = await actions.submit_document(
                NewDocument(**payload.model_dump(exclude={"invitation_id"})),
                key,
                invitation_id=payload.invitation_id,
            )
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        return AcceptedDocument(
            document=DocumentResponse(**document.model_dump()),
            processing=ProcessingResponse.from_record(record),
        )

    @router.post("/v2/documents/files", response_model=AcceptedDocument, status_code=202)
    async def submit_document_file(
        file: Annotated[UploadFile, File()],
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
        limits=Depends(get_limits),
        document_id: Annotated[UUID | None, Form()] = None,
        authored_at: Annotated[datetime | None, Form()] = None,
    ):
        content = await read_upload(file, limits.document_max_upload_bytes)
        try:
            document, record = await actions.submit_file(
                file.filename, content, document_id, authored_at, key
            )
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        return AcceptedDocument(
            document=DocumentResponse(**document.model_dump()),
            processing=ProcessingResponse.from_record(record),
        )

    @router.post("/v2/audio-notes", response_model=AcceptedAudio, status_code=202)
    async def submit_audio(
        file: Annotated[UploadFile, File()],
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
        limits=Depends(get_limits),
        authored_at: Annotated[datetime | None, Form()] = None,
        invitation_id: Annotated[UUID | None, Form()] = None,
    ):
        content = await read_upload(file, limits.audio_max_upload_bytes)
        try:
            note, record = await actions.submit_audio(
                file.filename,
                file.content_type,
                content,
                authored_at,
                key,
                invitation_id=invitation_id,
            )
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        return AcceptedAudio(
            audio_note=AudioSnapshot(**note.model_dump()),
            processing=ProcessingResponse.from_record(record),
        )

    @router.get("/processing", response_model=ProcessingPage)
    async def list_processing(
        actions=Depends(get_actions),
        active: bool = False,
        cursor: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        try:
            rows = await actions.list(active=active, cursor=cursor, limit=limit + 1)
        except Exception as error:
            raise http_error(error) from error
        return ProcessingPage(
            items=[ProcessingResponse.from_record(row) for row in rows[:limit]],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None,
        )

    @router.get("/processing/{processing_id}", response_model=ProcessingResponse)
    async def get_processing(processing_id: UUID, actions=Depends(get_actions)):
        try:
            return ProcessingResponse.from_record(await actions.get(processing_id))
        except Exception as error:
            raise http_error(error) from error

    @router.get("/processing/{processing_id}/extractors", response_model=list[ProcessingResponse])
    async def extractor_states(processing_id: UUID, actions=Depends(get_actions)):
        try:
            return [
                ProcessingResponse.from_record(child)
                for child in await actions.children(processing_id)
            ]
        except Exception as error:
            raise http_error(error) from error

    @router.post(
        "/processing/{processing_id}/retry", response_model=ProcessingResponse, status_code=202
    )
    async def retry_processing(
        processing_id: UUID,
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
    ):
        try:
            record = await actions.retry(processing_id, key)
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        response.status_code = 202 if actions.changed else 200
        return ProcessingResponse.from_record(record)

    @router.post(
        "/v2/documents/{document_id}/processing", response_model=ProcessingResponse, status_code=202
    )
    async def request_document_processing(
        document_id: UUID,
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
    ):
        try:
            record = await actions.reprocess_document(document_id, key)
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        return ProcessingResponse.from_record(record)

    @router.post(
        "/v2/documents/reprocess", response_model=ReprocessDocumentsResponse, status_code=202
    )
    async def reprocess_documents(
        payload: ReprocessDocumentsRequest,
        key: Key,
        actions=Depends(get_actions),
    ):
        try:
            records = await actions.reprocess_documents(payload.document_ids, key)
        except Exception as error:
            raise http_error(error) from error
        return ReprocessDocumentsResponse(
            items=[ProcessingResponse.from_record(record) for record in records]
        )

    @router.get("/v2/documents", response_model=list[DocumentSnapshot])
    async def document_snapshots(actions=Depends(get_actions)):
        try:
            return [
                DocumentSnapshot(
                    **document.model_dump(),
                    processing=ProcessingResponse.from_record(record) if record else None,
                )
                for document, record in await actions.documents()
            ]
        except Exception as error:
            raise http_error(error) from error

    @router.get("/v2/documents/{document_id}", response_model=DocumentSnapshot)
    async def document_snapshot(document_id: UUID, actions=Depends(get_actions)):
        try:
            document, record = await actions.document(document_id)
        except Exception as error:
            raise http_error(error) from error
        return DocumentSnapshot(
            **document.model_dump(),
            processing=ProcessingResponse.from_record(record) if record else None,
        )

    @router.get("/v2/audio-notes/{audio_note_id}", response_model=AudioSnapshot)
    async def audio_snapshot(audio_note_id: UUID, actions=Depends(get_actions)):
        try:
            note, record = await actions.audio_note(audio_note_id)
        except Exception as error:
            raise http_error(error) from error
        return AudioSnapshot(
            **note.model_dump(),
            processing=ProcessingResponse.from_record(record) if record else None,
        )

    @router.post(
        "/v2/audio-notes/{audio_note_id}/documents",
        response_model=ProcessingResponse,
        status_code=202,
    )
    async def recover_audio_document(
        audio_note_id: UUID,
        key: Key,
        request: Request,
        response: Response,
        actions=Depends(get_actions),
    ):
        try:
            record = await actions.recover_audio(audio_note_id, key)
        except Exception as error:
            raise http_error(error) from error
        accepted_headers(request, response, record)
        response.status_code = 202 if actions.changed else 200
        return ProcessingResponse.from_record(record)

    return router
