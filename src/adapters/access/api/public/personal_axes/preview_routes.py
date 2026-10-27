"""Temporary preview HTTP operations through the injected application."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from src.adapters.access.api.public.personal_axes.responses import axis_response
from src.adapters.access.api.public.personal_axes.routes import respond
from src.adapters.access.api.public.personal_axes.schemas import (
    AxisResponse,
    PreviewNeighbors,
    PreviewResults,
    PreviewSnapshot,
)
from src.core.extractors.personal_axes.models import AcceptPreview, PreviewRequest
from src.use_cases.personal_axes.previews import AxisPreviews


def build_router(get_previews, same_origin):
    router = APIRouter(tags=["personal axes"], dependencies=[Depends(same_origin)])
    Service = Annotated[AxisPreviews, Depends(get_previews)]
    IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]

    @router.post("/laboratory/axis-previews", status_code=202, response_model=PreviewSnapshot)
    @respond
    async def create_preview(body: PreviewRequest, service: Service, key: IdempotencyKey):
        return await service.request(body, key)

    @router.get("/laboratory/axis-previews/{preview_id}", response_model=PreviewSnapshot)
    @respond
    async def preview(preview_id: UUID, service: Service):
        return await service.snapshot(preview_id)

    @router.get("/laboratory/axis-previews/{preview_id}/results", response_model=PreviewResults)
    @respond
    async def preview_results(preview_id: UUID, service: Service):
        return await service.results(preview_id)

    @router.post("/laboratory/axis-previews/{preview_id}/retry", response_model=PreviewSnapshot)
    @respond
    async def retry_preview(preview_id: UUID, service: Service, key: IdempotencyKey):
        return await service.retry(preview_id, key)

    @router.post("/laboratory/axis-previews/{preview_id}/accept", response_model=AxisResponse)
    @respond
    async def accept_preview(preview_id: UUID, body: AcceptPreview, service: Service):
        return axis_response(await service.accept(preview_id, body.revision_hash))

    @router.get("/laboratory/axis-previews/{preview_id}/neighbors", response_model=PreviewNeighbors)
    @respond
    async def axis_preview_neighbors(
        preview_id: UUID,
        service: Service,
        node_id: str | None = Query(None, max_length=2048),
        cursor: str | None = Query(None, max_length=4096),
        limit: int = Query(30, ge=1, le=100),
    ):
        return await service.preview_neighbors(preview_id, node_id, cursor, limit)

    return router
