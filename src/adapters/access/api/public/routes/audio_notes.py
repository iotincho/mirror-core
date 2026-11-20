"""Read original audio; mutation uses the durable /v2 routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.adapters.access.api.public.schemas.audio_notes import AudioNoteResponse
from src.core.audio.errors import AudioNoteNotFoundError
from src.core.audio.ports import AudioNoteStore
from src.core.graph.ports import GraphPersistenceError
from src.core.processing.errors import StorageUnavailable
from src.core.processing.submissions import SubmissionConflict
from src.use_cases.audio.delete_audio_entry import DeleteAudioEntry


def build_router(get_audio_note_store, get_delete_audio_entry):
    router = APIRouter(tags=["audio-notes"])

    @router.get("/audio-notes/{audio_note_id}", response_model=AudioNoteResponse)
    async def get_audio_note(
        audio_note_id: UUID,
        store: Annotated[AudioNoteStore, Depends(get_audio_note_store)],
    ) -> AudioNoteResponse:
        try:
            note = await store.get(audio_note_id)
        except AudioNoteNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return AudioNoteResponse(**note.model_dump())

    @router.delete("/v2/audio-notes/{audio_note_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_audio_entry(
        audio_note_id: UUID,
        use_case: Annotated[DeleteAudioEntry, Depends(get_delete_audio_entry)],
        by_upload_key: bool = False,
    ) -> None:
        try:
            await use_case.execute(audio_note_id, by_upload_key=by_upload_key)
        except AudioNoteNotFoundError as error:
            raise HTTPException(404, "Audio entry not found") from error
        except SubmissionConflict as error:
            raise HTTPException(409, str(error)) from error
        except (StorageUnavailable, GraphPersistenceError, OSError) as error:
            raise HTTPException(503, "Unable to delete entry") from error

    return router
