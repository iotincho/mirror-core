from fastapi import APIRouter, Depends

from src.adapters.access.api.public.routes import (
    audio_notes,
    document_archive,
    documents,
    events,
    graph,
    processing,
    retired,
    system,
)
from src.bootstrap import public_dependencies as deps
from src.bootstrap.auth import require_authenticated
from src.bootstrap.auth import router as auth_router
from src.bootstrap.personal_axes_api import router as axes_router
from src.bootstrap.public_channels import activity_router, invitation_router, notification_router
from src.bootstrap.workspaces import router as workspace_router

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth_router)
api_router.include_router(activity_router)
api_router.include_router(workspace_router)
# Events perform the same cookie checks in short sessions, also during the stream.
api_router.include_router(events.build_router(deps.get_stream_authorization, deps.get_event_feed))
protected_router = APIRouter(dependencies=[Depends(require_authenticated)])
protected_router.include_router(axes_router)
protected_router.include_router(invitation_router)
protected_router.include_router(notification_router)
protected_router.include_router(
    document_archive.build_router(deps.get_export_archive, deps.get_import_archive)
)
protected_router.include_router(
    documents.build_router(deps.get_delete_document, deps.get_list_documents)
)
protected_router.include_router(audio_notes.build_router(deps.get_audio_note_store))
protected_router.include_router(
    processing.build_router(deps.get_public_processing, deps.get_upload_limits)
)
protected_router.include_router(graph.build_router(deps.get_document_store, deps.get_graph_store))
protected_router.include_router(retired.router)
api_router.include_router(protected_router)
