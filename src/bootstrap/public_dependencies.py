"""Composition for original document access; processing owns transcription clients."""

from typing import Annotated

from fastapi import Depends

from src.adapters.storage.filesystem.audio_notes import FileAudioNoteStore
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_async_session
from src.bootstrap.processing import get_repository
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.graph.ports import GraphBackend
from src.core.workspaces.context import WorkspaceRuntime


async def get_document_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileDocumentStore:
    return runtime.document_store


async def get_audio_note_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileAudioNoteStore:
    return runtime.audio_note_store


async def get_graph_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> GraphBackend:
    return runtime.graph_store


async def get_delete_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
    from src.bootstrap.archives import build_delete_document as DeleteDocument
    from src.bootstrap.processing import get_repository

    return DeleteDocument(
        document_store,
        graph_store,
        get_repository(),
        runtime.context.user_id,
        layer_artifacts=LayerArtifacts(runtime.context.filesystem_root / "layers"),
    )


async def get_list_documents(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.documents import build_title_scheduler as EnsureDocumentTitles
    from src.bootstrap.processing import get_repository
    from src.use_cases.documents.list_documents import ListDocuments

    return ListDocuments(document_store, EnsureDocumentTitles(get_repository(), runtime))


def get_upload_limits():
    from src.adapters.access.api.public.schemas.processing import UploadLimits
    from src.bootstrap.settings import get_settings

    settings = get_settings()
    return UploadLimits(document_max_upload_bytes=settings.document_max_upload_bytes,
                        audio_max_upload_bytes=settings.audio_max_upload_bytes)


def get_public_processing(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    repository=Depends(get_repository),
    limits=Depends(get_upload_limits),
):
    from src.adapters.storage.postgres.reads import PostgresProcessingReads
    from src.adapters.storage.postgres.submissions import SubmissionRepository
    from src.bootstrap.acceptance import SubmitAudioNote, SubmitDocument
    from src.bootstrap.documents import build_title_scheduler
    from src.bootstrap.processing import build_processing_requests
    from src.use_cases.processing.public import PublicProcessing

    submissions = SubmissionRepository(repository)
    return PublicProcessing(
        runtime,
        PostgresProcessingReads(repository),
        SubmitDocument(submissions, runtime),
        SubmitAudioNote(submissions, runtime, limits.audio_max_upload_bytes),
        build_processing_requests(repository, runtime),
        build_title_scheduler(repository, runtime),
    )


def get_stream_authorization():
    from src.adapters.storage.postgres.stream_sessions import PostgresStreamSessions
    from src.bootstrap.database import get_session_maker
    from src.bootstrap.settings import get_settings
    from src.use_cases.auth.authorize_stream import AuthorizeStream

    settings = get_settings()
    return AuthorizeStream(
        PostgresStreamSessions(get_session_maker(), settings.auth_session_ttl_seconds),
        settings.arcadedb_instance_key,
    )


def get_event_feed():
    from src.adapters.storage.postgres.events import EventFeed
    from src.bootstrap.database import get_session_maker

    return EventFeed(get_session_maker())


async def get_archive_store(
    user=Depends(get_authenticated_user),
    session=Depends(get_async_session),
):
    from fastapi import HTTPException

    from src.adapters.storage.filesystem.owner_originals import FileOwnerOriginals
    from src.adapters.storage.postgres.workspaces import PostgresWorkspaces
    from src.bootstrap.settings import get_settings
    from src.core.documents.original_access import OriginalStorageUnavailable
    from src.core.workspaces.models import WorkspaceUnavailable
    from src.use_cases.documents.resolve_originals import ResolveOriginals

    settings = get_settings()
    resolver = ResolveOriginals(
        PostgresWorkspaces(None, session=session),
        FileOwnerOriginals(settings.workspaces_path),
        settings.arcadedb_instance_key,
    )
    try:
        return await resolver.execute(user.id)
    except WorkspaceUnavailable as error:
        raise HTTPException(503, error.detail) from error
    except OriginalStorageUnavailable as error:
        raise HTTPException(503, "Original document storage is unavailable") from error


def get_export_archive(store=Depends(get_archive_store)):
    from src.bootstrap.archives import DocumentArchiveTransfer

    return DocumentArchiveTransfer(store)


def get_import_archive(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    repository=Depends(get_repository),
):
    from src.bootstrap.archives import DocumentArchiveTransfer

    return DocumentArchiveTransfer(
        runtime.document_store,
        repository,
        runtime.context.user_id,
        graph=runtime.graph_store,
    )
