"""Composition for original document access; processing owns transcription clients."""

from typing import Annotated

from fastapi import Depends

from src.services.audio_note_store import FileAudioNoteStore
from src.services.document_store import FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.services.graph_store import GraphBackend
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime


async def close_provider_clients() -> None:
    """The HTTP API no longer owns model clients; workers close their providers."""


async def get_document_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileDocumentStore:
    return runtime.document_store


async def get_audio_note_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileAudioNoteStore:
    return runtime.audio_note_store


async def get_extraction_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileExtractionStore:
    return runtime.extraction_store


async def get_graph_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> GraphBackend:
    return runtime.graph_store


async def get_delete_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    extraction_store: Annotated[FileExtractionStore, Depends(get_extraction_store)],
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.processing.runtime import get_repository
    from src.use_cases.delete_document import DeleteDocument

    return DeleteDocument(
        document_store, extraction_store, graph_store, get_repository(), runtime.context.user_id
    )


async def get_list_documents(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
):
    from src.use_cases.list_documents import ListDocuments

    return ListDocuments(document_store)
