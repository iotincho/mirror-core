"""Experimental, authenticated backend; no changes to existing constellation routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from src.adapters.access.api.public.personal_axes.schemas import (
    AxisResponse,
    PreviewNeighbors,
    PreviewResults,
    PreviewSnapshot,
)
from src.bootstrap.public_security import require_same_origin
from src.core.extractors.personal_axes.models import AcceptPreview, PreviewRequest
from src.extractors.personal_axes.dependencies import get_axis_previews
from src.extractors.personal_axes.exploration import preview_neighbors
from src.extractors.personal_axes.history import AxisHistory
from src.extractors.personal_axes.history_schemas import (
    HistoryBatchPage,
    HistoryBatchView,
    HistoryCandidates,
    HistoryRequest,
)
from src.use_cases.axis_previews import AxisPreviews

router = APIRouter(tags=["personal axes"], dependencies=[Depends(require_same_origin)])
Service = Annotated[AxisPreviews, Depends(get_axis_previews)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("/laboratory/axis-previews", status_code=202, response_model=PreviewSnapshot)
async def create_preview(body: PreviewRequest, service: Service, key: IdempotencyKey):
    return await service.request(body, key)


@router.get("/laboratory/axis-previews/{preview_id}", response_model=PreviewSnapshot)
async def preview(preview_id: UUID, service: Service):
    return await service.snapshot(preview_id)


@router.get("/laboratory/axis-previews/{preview_id}/results", response_model=PreviewResults)
async def preview_results(preview_id: UUID, service: Service):
    return await service.results(preview_id)


@router.post("/laboratory/axis-previews/{preview_id}/retry", response_model=PreviewSnapshot)
async def retry_preview(preview_id: UUID, service: Service, key: IdempotencyKey):
    return await service.retry(preview_id, key)


@router.post("/laboratory/axis-previews/{preview_id}/accept", response_model=AxisResponse)
async def accept_preview(preview_id: UUID, body: AcceptPreview, service: Service):
    return await service.accept(preview_id, body.revision_hash)


@router.get("/personal-axes/{axis_id}/history/notes", response_model=HistoryCandidates)
async def history_notes(
    axis_id: UUID,
    service: Service,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    q: str = Query("", max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
):
    return await AxisHistory(service).notes(axis_id, offset, limit, q.strip(), date_from, date_to)


@router.get("/personal-axes/{axis_id}/history/batches", response_model=HistoryBatchPage)
async def history_batches(
    axis_id: UUID,
    service: Service,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=30),
):
    return await AxisHistory(service).batches(axis_id, offset, limit)


@router.post(
    "/personal-axes/{axis_id}/history/batches", response_model=HistoryBatchView, status_code=202
)
async def start_history(axis_id: UUID, body: HistoryRequest, key: IdempotencyKey, service: Service):
    return await AxisHistory(service).start(axis_id, body, key)


@router.get("/personal-axes/{axis_id}/history/batches/{batch_id}", response_model=HistoryBatchView)
async def history_batch(
    axis_id: UUID,
    batch_id: UUID,
    service: Service,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await AxisHistory(service).snapshot(axis_id, batch_id, offset, limit)


@router.post(
    "/personal-axes/{axis_id}/history/batches/{batch_id}/stop", response_model=HistoryBatchView
)
async def stop_history(axis_id: UUID, batch_id: UUID, service: Service):
    return await AxisHistory(service).stop(axis_id, batch_id)


@router.post(
    "/personal-axes/{axis_id}/history/batches/{batch_id}/retry", response_model=HistoryBatchView
)
async def retry_history(axis_id: UUID, batch_id: UUID, key: IdempotencyKey, service: Service):
    return await AxisHistory(service).retry(axis_id, batch_id, key)


@router.get("/laboratory/axis-previews/{preview_id}/neighbors", response_model=PreviewNeighbors)
async def axis_preview_neighbors(
    preview_id: UUID,
    service: Service,
    node_id: str | None = Query(None, max_length=2048),
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(30, ge=1, le=100),
):
    return await preview_neighbors(service, preview_id, node_id, cursor, limit)
