"""Voice-note upload and asynchronous transcription endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import ValidationError

from src.api.schemas.audio_notes import AudioNoteResponse
from src.dependencies import get_audio_note_store, get_create_audio_note, get_transcribe_audio_note
from src.services.audio_note_store import AudioNoteNotFoundError, FileAudioNoteStore
from src.use_cases.transcribe_audio_note import (
    AudioFileTooLargeError,
    CreateAudioNote,
    TranscribeAudioNote,
    UnsupportedAudioFileError,
)

router = APIRouter(prefix="/audio-notes", tags=["audio-notes"])


@router.post("", response_model=AudioNoteResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_audio_note(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Completed voice note")],
    create_use_case: Annotated[CreateAudioNote, Depends(get_create_audio_note)],
    transcribe_use_case: Annotated[TranscribeAudioNote, Depends(get_transcribe_audio_note)],
    authored_at: Annotated[datetime | None, Form()] = None,
) -> AudioNoteResponse:
    """Persist completed audio and start transcription after responding."""
    try:
        note = create_use_case.execute(
            file.filename,
            file.content_type,
            await file.read(),
            authored_at,
        )
    except UnsupportedAudioFileError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except AudioFileTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(error),
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error.errors(),
        ) from error

    background_tasks.add_task(transcribe_use_case.execute, note.id)
    return AudioNoteResponse(**note.model_dump())


@router.get("/{audio_note_id}", response_model=AudioNoteResponse)
async def get_audio_note(
    audio_note_id: UUID,
    store: Annotated[FileAudioNoteStore, Depends(get_audio_note_store)],
) -> AudioNoteResponse:
    try:
        note = store.get(audio_note_id)
    except AudioNoteNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return AudioNoteResponse(**note.model_dump())


@router.post(
    "/{audio_note_id}/documents",
    response_model=AudioNoteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_audio_document_persistence(
    audio_note_id: UUID,
    background_tasks: BackgroundTasks,
    store: Annotated[FileAudioNoteStore, Depends(get_audio_note_store)],
    transcribe_use_case: Annotated[TranscribeAudioNote, Depends(get_transcribe_audio_note)],
) -> AudioNoteResponse:
    """Retry document creation for an already transcribed audio note."""
    try:
        note = store.get(audio_note_id)
    except AudioNoteNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    if note.status != "completed" or note.transcript is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio transcription has not completed",
        )
    if note.document_id is not None:
        return AudioNoteResponse(**note.model_dump())

    background_tasks.add_task(transcribe_use_case.execute, note.id)
    return AudioNoteResponse(**note.model_dump())
