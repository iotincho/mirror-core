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
from sqlalchemy.exc import SQLAlchemyError

from src.api.schemas.documents import CreateDocumentRequest, DocumentResponse
from src.api.schemas.processing import (
    AcceptedAudio,
    AcceptedDocument,
    AudioSnapshot,
    DocumentSnapshot,
    ProcessingPage,
    ProcessingResponse,
)
from src.config import get_settings
from src.domain.documents import NewDocument
from src.processing.runtime import get_repository
from src.processing.submissions import SubmissionConflict, SubmissionRepository
from src.services.audio_note_store import AudioNoteNotFoundError
from src.services.document_store import DocumentNotFoundError
from src.use_cases.create_audio_note import AudioFileTooLargeError, UnsupportedAudioFileError
from src.use_cases.ingest_document_file import (
    IngestDocumentFile,
    InvalidDocumentEncodingError,
    UnsupportedDocumentFileError,
)
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import SubmitAudioNote, SubmitDocument
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime

router = APIRouter(tags=["processing"])
Runtime = Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def http_error(error):
    if isinstance(error, (DocumentNotFoundError, AudioNoteNotFoundError)):
        return HTTPException(404, "Resource not found")
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
    if isinstance(error, SQLAlchemyError):
        return HTTPException(
            503, "Processing storage unavailable; retry with the same Idempotency-Key"
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


@router.post("/v2/documents", response_model=AcceptedDocument, status_code=202)
async def submit_document(
    payload: CreateDocumentRequest, runtime: Runtime, key: Key, request: Request, response: Response
):
    if len(payload.content.encode()) > get_settings().document_max_upload_bytes:
        raise HTTPException(413, "Upload exceeds configured size limit")
    try:
        document, record = await SubmitDocument(
            SubmissionRepository(get_repository()), runtime
        ).execute(NewDocument(**payload.model_dump()), key)
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
    runtime: Runtime,
    key: Key,
    request: Request,
    response: Response,
    document_id: Annotated[UUID | None, Form()] = None,
    authored_at: Annotated[datetime | None, Form()] = None,
):
    content = await read_upload(file, get_settings().document_max_upload_bytes)
    try:
        original = IngestDocumentFile(runtime.document_store).build_new_document(
            file.filename, content, document_id, authored_at
        )
        document, record = await SubmitDocument(
            SubmissionRepository(get_repository()), runtime
        ).execute(original, key)
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
    runtime: Runtime,
    key: Key,
    request: Request,
    response: Response,
    authored_at: Annotated[datetime | None, Form()] = None,
):
    settings = get_settings()
    content = await read_upload(file, settings.audio_max_upload_bytes)
    try:
        note, record = await SubmitAudioNote(
            SubmissionRepository(get_repository()), runtime, settings.audio_max_upload_bytes
        ).execute(file.filename, file.content_type, content, authored_at, key)
    except Exception as error:
        raise http_error(error) from error
    accepted_headers(request, response, record)
    return AcceptedAudio(
        audio_note=AudioSnapshot(**note.model_dump()),
        processing=ProcessingResponse.from_record(record),
    )


@router.get("/processing", response_model=ProcessingPage)
async def list_processing(
    runtime: Runtime,
    active: bool = False,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    try:
        rows = await get_repository().list_for_owner(
            runtime.context.user_id, active=active, cursor=cursor, limit=limit + 1
        )
    except Exception as error:
        raise http_error(error) from error
    return ProcessingPage(
        items=[ProcessingResponse.from_record(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/processing/{processing_id}", response_model=ProcessingResponse)
async def get_processing(processing_id: UUID, runtime: Runtime):
    record = await get_repository().get(processing_id, runtime.context.user_id)
    if record is None:
        raise HTTPException(404, "Processing not found")
    return ProcessingResponse.from_record(record)


@router.post(
    "/processing/{processing_id}/retry", response_model=ProcessingResponse, status_code=202
)
async def retry_processing(
    processing_id: UUID, runtime: Runtime, key: Key, request: Request, response: Response
):
    try:
        use_case = RequestProcessing(get_repository(), runtime)
        record = await use_case.retry(processing_id, key)
    except Exception as error:
        raise http_error(error) from error
    accepted_headers(request, response, record)
    response.status_code = 202 if use_case.changed else 200
    return ProcessingResponse.from_record(record)


@router.post(
    "/v2/documents/{document_id}/processing", response_model=ProcessingResponse, status_code=202
)
async def request_document_processing(
    document_id: UUID,
    runtime: Runtime,
    key: Key,
    request: Request,
    response: Response,
):
    try:
        record = await RequestProcessing(get_repository(), runtime).reprocess_document(
            document_id, key
        )
    except Exception as error:
        raise http_error(error) from error
    accepted_headers(request, response, record)
    return ProcessingResponse.from_record(record)


@router.get("/v2/documents", response_model=list[DocumentSnapshot])
async def document_snapshots(runtime: Runtime):
    snapshots = []
    for document in await runtime.document_store.list():
        record = await get_repository().latest(runtime.context.user_id, document.id, "document")
        snapshots.append(
            DocumentSnapshot(
                **document.model_dump(),
                processing=ProcessingResponse.from_record(record) if record else None,
            )
        )
    return snapshots


@router.get("/v2/documents/{document_id}", response_model=DocumentSnapshot)
async def document_snapshot(document_id: UUID, runtime: Runtime):
    try:
        document = await runtime.document_store.get(document_id)
    except DocumentNotFoundError as error:
        raise http_error(error) from error
    record = await get_repository().latest(runtime.context.user_id, document_id, "document")
    return DocumentSnapshot(
        **document.model_dump(),
        processing=ProcessingResponse.from_record(record) if record else None,
    )


@router.get("/v2/audio-notes/{audio_note_id}", response_model=AudioSnapshot)
async def audio_snapshot(audio_note_id: UUID, runtime: Runtime):
    try:
        note = await runtime.audio_note_store.get(audio_note_id)
    except AudioNoteNotFoundError as error:
        raise http_error(error) from error
    record = await get_repository().latest(runtime.context.user_id, audio_note_id, "audio")
    return AudioSnapshot(
        **note.model_dump(), processing=ProcessingResponse.from_record(record) if record else None
    )


@router.post(
    "/v2/audio-notes/{audio_note_id}/documents", response_model=ProcessingResponse, status_code=202
)
async def recover_audio_document(
    audio_note_id: UUID, runtime: Runtime, key: Key, request: Request, response: Response
):
    try:
        use_case = RequestProcessing(get_repository(), runtime)
        record = await use_case.recover_audio(audio_note_id, key)
    except Exception as error:
        raise http_error(error) from error
    accepted_headers(request, response, record)
    response.status_code = 202 if use_case.changed else 200
    return ProcessingResponse.from_record(record)
