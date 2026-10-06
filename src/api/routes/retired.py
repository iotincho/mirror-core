"""Explicit retirement responses without constructing exploratory providers."""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["retired"])


async def extraction_retired():
    raise HTTPException(410, "Exploratory extraction has been retired. Originals remain available.")


for path in (
    "/search",
    "/search/{path:path}",
    "/resolve",
    "/documents/{document_id}/extractions",
    "/documents/{document_id}/extractions/{path:path}",
    "/documents/{document_id}/links",
    "/v2/documents/{document_id}/extractions",
):
    router.add_api_route(path, extraction_retired, methods=["GET", "POST"], include_in_schema=False)


async def durable_upload_required():
    raise HTTPException(410, "Use the /v2 ingestion routes with an Idempotency-Key.")


for path in ("/documents", "/documents/files", "/audio-notes", "/audio-notes/{id}/documents"):
    router.add_api_route(path, durable_upload_required, methods=["POST"], include_in_schema=False)
