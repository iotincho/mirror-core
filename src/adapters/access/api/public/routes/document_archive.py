"""Download and restore portable originals for the authenticated account."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import ValidationError

from src.core.documents.archive import ArchiveConflict, DocumentArchive
from src.core.graph.ports import GraphPersistenceError
from src.core.processing.errors import StorageUnavailable
from src.core.processing.submissions import SubmissionConflict

MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


def build_router(get_export_archive, get_import_archive):
    router = APIRouter(prefix="/documents", tags=["documents"])

    @router.get("/export")
    async def export_documents(transfer=Depends(get_export_archive)):
        archive = await transfer.export()
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
        transfer=Depends(get_import_archive),
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
            return await transfer.import_archive(archive)
        except (ArchiveConflict, SubmissionConflict) as error:
            raise HTTPException(409, str(error)) from error
        except StorageUnavailable as error:
            raise HTTPException(
                503, "No se pudo encolar la extracción. Reintentá el mismo archivo."
            ) from error
        except GraphPersistenceError as error:
            raise HTTPException(
                503, "No se pudo confirmar el documento en el grafo. Reintentá el mismo archivo."
            ) from error

    return router
