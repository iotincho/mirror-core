"""Historical batch HTTP compatibility until stage 4."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from src.bootstrap.personal_axes_dependencies import get_axis_previews
from src.bootstrap.public_security import require_same_origin
from src.extractors.personal_axes.history import AxisHistory
from src.extractors.personal_axes.history_schemas import (
    HistoryBatchPage,
    HistoryBatchView,
    HistoryCandidates,
    HistoryRequest,
)

router = APIRouter(tags=["personal axes"], dependencies=[Depends(require_same_origin)])
Service = Annotated[object, Depends(get_axis_previews)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


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
