"""Read original audio; mutation uses the durable /v2 routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.adapters.access.api.public.schemas.audio_notes import AudioNoteResponse
from src.core.audio.errors import AudioNoteNotFoundError
from src.core.audio.ports import AudioNoteStore


def build_router(get_audio_note_store):
    router = APIRouter(prefix="/audio-notes", tags=["audio-notes"])

    @router.get("/{audio_note_id}", response_model=AudioNoteResponse)
    async def get_audio_note(
        audio_note_id: UUID,
        store: Annotated[AudioNoteStore, Depends(get_audio_note_store)],
    ) -> AudioNoteResponse:
        try:
            note = await store.get(audio_note_id)
        except AudioNoteNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return AudioNoteResponse(**note.model_dump())

    return router
