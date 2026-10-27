"""Historical batch HTTP compatibility until stage 4."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from src.adapters.access.api.public.personal_axes.history_schemas import (
    HistoryBatchPage,
    HistoryBatchView,
    HistoryCandidates,
    HistoryRequest,
)
from src.adapters.access.api.public.personal_axes.routes import respond
from src.use_cases.personal_axes.history import AxisHistory


def build_router(get_history, same_origin):
    router = APIRouter(tags=["personal axes"], dependencies=[Depends(same_origin)])
    Service = Annotated[AxisHistory, Depends(get_history)]
    IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]

    @router.get("/personal-axes/{axis_id}/history/notes", response_model=HistoryCandidates)
    @respond
    async def history_notes(
        axis_id: UUID,
        service: Service,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        q: str = Query("", max_length=200),
        date_from: date | None = None,
        date_to: date | None = None,
    ):
        return await service.notes(axis_id, offset, limit, q.strip(), date_from, date_to)

    @router.get("/personal-axes/{axis_id}/history/batches", response_model=HistoryBatchPage)
    @respond
    async def history_batches(
        axis_id: UUID,
        service: Service,
        offset: int = Query(0, ge=0),
        limit: int = Query(10, ge=1, le=30),
    ):
        return await service.batches(axis_id, offset, limit)

    @router.post(
        "/personal-axes/{axis_id}/history/batches", response_model=HistoryBatchView, status_code=202
    )
    @respond
    async def start_history(
        axis_id: UUID, body: HistoryRequest, key: IdempotencyKey, service: Service
    ):
        return await service.start(axis_id, body, key)

    @router.get(
        "/personal-axes/{axis_id}/history/batches/{batch_id}", response_model=HistoryBatchView
    )
    @respond
    async def history_batch(
        axis_id: UUID,
        batch_id: UUID,
        service: Service,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ):
        return await service.snapshot(axis_id, batch_id, offset, limit)

    @router.post(
        "/personal-axes/{axis_id}/history/batches/{batch_id}/stop", response_model=HistoryBatchView
    )
    @respond
    async def stop_history(axis_id: UUID, batch_id: UUID, service: Service):
        return await service.stop(axis_id, batch_id)

    @router.post(
        "/personal-axes/{axis_id}/history/batches/{batch_id}/retry", response_model=HistoryBatchView
    )
    @respond
    async def retry_history(axis_id: UUID, batch_id: UUID, key: IdempotencyKey, service: Service):
        return await service.retry(axis_id, batch_id, key)

    return router
