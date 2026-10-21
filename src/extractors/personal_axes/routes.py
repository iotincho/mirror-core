"""Experimental, authenticated backend; no changes to existing constellation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from src.extractors.personal_axes.contracts import AcceptPreview, PreviewRequest
from src.extractors.personal_axes.dependencies import get_axis_previews
from src.extractors.personal_axes.exploration import AxisExploration, preview_neighbors
from src.extractors.personal_axes.schemas import (
    ActiveFinding,
    ActiveFindingsPage,
    ActiveNeighbors,
    AxesPage,
    AxisEnabled,
    AxisResponse,
    AxisTagsPage,
    PreviewNeighbors,
    PreviewResults,
    PreviewSnapshot,
)
from src.use_cases.axis_previews import AxisPreviews

router = APIRouter(tags=["personal axes"])
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


@router.get("/personal-axes", response_model=AxesPage)
async def list_axes(
    service: Service, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return await service.axes.list(service.owner, offset, limit)


@router.get("/personal-axes/{axis_id}", response_model=AxisResponse)
async def get_axis(axis_id: UUID, service: Service):
    return await service.axes.get(service.owner, axis_id)


@router.patch("/personal-axes/{axis_id}", response_model=AxisResponse)
async def set_axis_enabled(axis_id: UUID, body: AxisEnabled, service: Service):
    return await service.axes.set_enabled(service.owner, axis_id, body.enabled)


@router.get("/personal-axes/{axis_id}/versions/{version_id}", response_model=AxisResponse)
async def axis_version(axis_id: UUID, version_id: UUID, service: Service):
    return await service.axes.version(service.owner, axis_id, version_id)


@router.get("/personal-axes/{axis_id}/tags", response_model=AxisTagsPage)
async def axis_tags(
    axis_id: UUID,
    service: Service,
    version_id: UUID | None = None,
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(50, ge=1, le=100),
):
    return await AxisExploration(service).tags(axis_id, version_id, cursor, limit)


@router.get("/personal-axes/{axis_id}/findings", response_model=ActiveFindingsPage)
async def axis_findings(
    axis_id: UUID,
    service: Service,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(30, ge=1, le=100),
):
    return await AxisExploration(service).findings(axis_id, version_id, document_id, cursor, limit)


@router.get("/personal-axes/{axis_id}/findings/{finding_id}", response_model=ActiveFinding)
async def axis_finding(
    axis_id: UUID,
    finding_id: UUID,
    service: Service,
    version_id: UUID | None = None,
):
    return await AxisExploration(service).finding(axis_id, finding_id, version_id)


@router.get("/personal-axes/{axis_id}/neighbors", response_model=ActiveNeighbors)
async def axis_neighbors(
    axis_id: UUID,
    service: Service,
    version_id: UUID | None = None,
    node_id: str | None = Query(None, max_length=2048),
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(30, ge=1, le=100),
):
    return await AxisExploration(service).neighbors(axis_id, node_id, version_id, cursor, limit)


@router.get("/laboratory/axis-previews/{preview_id}/neighbors", response_model=PreviewNeighbors)
async def axis_preview_neighbors(
    preview_id: UUID,
    service: Service,
    node_id: str | None = Query(None, max_length=2048),
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(30, ge=1, le=100),
):
    return await preview_neighbors(service, preview_id, node_id, cursor, limit)
