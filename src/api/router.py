from fastapi import APIRouter, Depends

from src.api.routes import (
    audio_notes,
    auth,
    document_archive,
    documents,
    events,
    graph,
    processing,
    retired,
    system,
)
from src.bootstrap.auth import require_authenticated
from src.bootstrap.public_channels import activity_router, invitation_router, notification_router
from src.bootstrap.workspaces import router as workspace_router
from src.extractors.personal_axes.routes import router as axes_router

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(activity_router)
api_router.include_router(workspace_router)
# Events perform the same cookie checks in short sessions, also during the stream.
api_router.include_router(events.router)
protected_router = APIRouter(dependencies=[Depends(require_authenticated)])
protected_router.include_router(axes_router)
protected_router.include_router(invitation_router)
protected_router.include_router(notification_router)
protected_router.include_router(document_archive.router)
protected_router.include_router(documents.router)
protected_router.include_router(audio_notes.router)
protected_router.include_router(processing.router)
protected_router.include_router(graph.router)
protected_router.include_router(retired.router)
api_router.include_router(protected_router)
