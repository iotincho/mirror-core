"""Download and restore portable originals for the authenticated account."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import ValidationError

from src.config import get_settings
from src.processing.runtime import get_repository
from src.services.document_store import FileDocumentStore
from src.services.graph_store import GraphPersistenceError
from src.use_cases.document_archive import ArchiveConflict, DocumentArchive, DocumentArchiveTransfer
from src.user_management.database import get_async_session
from src.user_management.dependencies import get_authenticated_user
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime
from src.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/documents", tags=["documents"])
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


async def get_archive_store(
    user=Depends(get_authenticated_user),
    session=Depends(get_async_session),
):
    # Export must remain available with an unavailable/suspended graph. Do not
    # decrypt graph credentials or require a successful ArcadeDB connection.
    settings = get_settings()
    workspace = await WorkspaceRepository(session).get(user.id)
    if workspace is None or workspace.arcadedb_instance_key != settings.arcadedb_instance_key:
        raise HTTPException(503, "Personal workspace is unavailable")
    root = settings.workspaces_path / str(user.id)
    directory = root / "documents"
    if (
        root.is_symlink()
        or directory.is_symlink()
        or any(p.is_symlink() for p in directory.glob("*"))
    ):
        raise HTTPException(503, "Original document storage is unavailable")
    return FileDocumentStore(directory)


@router.get("/export")
async def export_documents(store=Depends(get_archive_store)):
    archive = await DocumentArchiveTransfer(store).export()
    payload = archive.model_dump_json(indent=2).encode("utf-8")
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, "Document archive exceeds the 25 MiB import limit")
    return Response(
        payload,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="el-espejo-documentos.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import")
async def import_documents(
    file: Annotated[UploadFile, File()],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
    processing=Depends(get_repository),
):
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data.extend(chunk)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "El archivo supera el límite de 25 MiB.")
    try:
        archive = DocumentArchive.model_validate_json(data)
    except ValidationError as error:
        # Never echo document content through validation errors.
        raise HTTPException(
            422, "Archivo de documentos inválido o de una versión incompatible."
        ) from error
    try:
        return await DocumentArchiveTransfer(
            runtime.document_store,
            runtime.graph_store,
            processing,
            runtime.context.user_id,
        ).import_archive(archive)
    except ArchiveConflict as error:
        raise HTTPException(409, str(error)) from error
    except GraphPersistenceError as error:
        raise HTTPException(
            503, "No se pudo completar la escritura en el grafo. Reintentá el mismo archivo."
        ) from error
