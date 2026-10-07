from fastapi import APIRouter, Depends

from src.api.routes import (
    audio_notes,
    auth,
    document_archive,
    documents,
    events,
    processing,
    retired,
    system,
)
from src.auth.session import require_authenticated

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
# Events perform the same cookie checks in short sessions, also during the stream.
api_router.include_router(events.router)
protected_router = APIRouter(dependencies=[Depends(require_authenticated)])
protected_router.include_router(document_archive.router)
protected_router.include_router(documents.router)
protected_router.include_router(audio_notes.router)
protected_router.include_router(processing.router)
protected_router.include_router(retired.router)
api_router.include_router(protected_router)
