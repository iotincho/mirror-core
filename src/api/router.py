from fastapi import APIRouter, Depends

from src.api.routes import (
    audio_notes,
    auth,
    constellation,
    documents,
    extractions,
    processing,
    reflections,
    search,
    system,
)
from src.auth.session import require_authenticated

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
protected_router = APIRouter(dependencies=[Depends(require_authenticated)])
protected_router.include_router(documents.router)
protected_router.include_router(audio_notes.router)
protected_router.include_router(extractions.router)
protected_router.include_router(constellation.router)
protected_router.include_router(search.router)
protected_router.include_router(reflections.router)
protected_router.include_router(processing.router)
api_router.include_router(protected_router)
