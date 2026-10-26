"""Public routes with injected application cases; no storage or preview dependencies."""

from functools import wraps
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.adapters.access.api.public.personal_axes.errors import axis_status
from src.adapters.access.api.public.personal_axes.responses import axis_response
from src.adapters.access.api.public.personal_axes.schemas import (
    ActiveFinding,
    ActiveFindingsPage,
    ActiveNeighbors,
    AxesPage,
    AxisEnabled,
    AxisResponse,
    AxisTagsPage,
    LaboratoryContext,
    LaboratoryPreferences,
    LaboratoryPreferenceUpdate,
)
from src.core.auth.identity import AuthenticatedUser
from src.core.extractors.personal_axes.models import AxisError
from src.use_cases.personal_axes.definitions import AxisDefinitions
from src.use_cases.personal_axes.exploration import AxisExploration
from src.use_cases.personal_axes.laboratory import Laboratory


def respond(function):
    @wraps(function)
    async def translated(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except AxisError as error:
            raise HTTPException(axis_status(error.code), error.code) from None

    return translated


def build_router(get_identity, get_laboratory, get_definitions, get_exploration, same_origin):
    router = APIRouter(tags=["personal axes"], dependencies=[Depends(same_origin)])
    Identity = Annotated[AuthenticatedUser, Depends(get_identity)]
    Lab = Annotated[Laboratory, Depends(get_laboratory)]
    Definitions = Annotated[AxisDefinitions, Depends(get_definitions)]
    Exploration = Annotated[AxisExploration, Depends(get_exploration)]

    @router.get("/laboratory/context", response_model=LaboratoryContext)
    @respond
    async def laboratory_context(user: Identity, laboratory: Lab):
        return await laboratory.context(user.id)

    @router.patch("/laboratory/preferences", response_model=LaboratoryPreferences)
    @respond
    async def laboratory_preferences(
        body: LaboratoryPreferenceUpdate, user: Identity, laboratory: Lab
    ):
        return await laboratory.dismiss_welcome(user.id)

    @router.get("/personal-axes", response_model=AxesPage)
    @respond
    async def list_axes(
        service: Definitions, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
    ):
        result = await service.list(offset, limit)
        return {
            "items": [axis_response(item) for item in result.items],
            "next_offset": result.next_offset,
        }

    @router.get("/personal-axes/{axis_id}", response_model=AxisResponse)
    @respond
    async def get_axis(axis_id: UUID, service: Definitions):
        return axis_response(await service.get(axis_id))

    @router.patch("/personal-axes/{axis_id}", response_model=AxisResponse)
    @respond
    async def set_axis_enabled(axis_id: UUID, body: AxisEnabled, service: Definitions):
        return axis_response(await service.set_enabled(axis_id, body.enabled))

    @router.get("/personal-axes/{axis_id}/versions/{version_id}", response_model=AxisResponse)
    @respond
    async def axis_version(axis_id: UUID, version_id: UUID, service: Definitions):
        return axis_response(await service.version(axis_id, version_id))

    @router.get("/personal-axes/{axis_id}/tags", response_model=AxisTagsPage)
    @respond
    async def axis_tags(
        axis_id: UUID,
        service: Exploration,
        version_id: UUID | None = None,
        cursor: str | None = Query(None, max_length=4096),
        limit: int = Query(50, ge=1, le=100),
    ):
        return await service.tags(axis_id, version_id, cursor, limit)

    @router.get("/personal-axes/{axis_id}/findings", response_model=ActiveFindingsPage)
    @respond
    async def axis_findings(
        axis_id: UUID,
        service: Exploration,
        version_id: UUID | None = None,
        document_id: UUID | None = None,
        cursor: str | None = Query(None, max_length=4096),
        limit: int = Query(30, ge=1, le=100),
    ):
        return await service.findings(axis_id, version_id, document_id, cursor, limit)

    @router.get("/personal-axes/{axis_id}/findings/{finding_id}", response_model=ActiveFinding)
    @respond
    async def axis_finding(
        axis_id: UUID,
        finding_id: UUID,
        service: Exploration,
        version_id: UUID | None = None,
    ):
        return await service.finding(axis_id, finding_id, version_id)

    @router.get("/personal-axes/{axis_id}/neighbors", response_model=ActiveNeighbors)
    @respond
    async def axis_neighbors(
        axis_id: UUID,
        service: Exploration,
        version_id: UUID | None = None,
        node_id: str | None = Query(None, max_length=2048),
        cursor: str | None = Query(None, max_length=4096),
        limit: int = Query(30, ge=1, le=100),
    ):
        return await service.neighbors(axis_id, node_id, version_id, cursor, limit)

    return router
