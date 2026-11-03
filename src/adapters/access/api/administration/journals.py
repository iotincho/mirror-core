"""Dedicated LAN routes; owner comes from the selected, verified administration account."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import ValidationError

from src.adapters.access.api.administration import journal_schemas as http
from src.adapters.access.api.administration.routes import require_admin_same_origin
from src.core.journals.administration import AdministrativeAdjustment
from src.core.journals.contracts import ActivateRun, ChangeLifecycle
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.use_cases.journals.administration import AdministerJournals


async def respond(action, *args):
    try:
        return await action(*args)
    except ValidationError:
        raise HTTPException(422, "journal_invalid_configuration") from None
    except JournalStorageUnavailable:
        raise HTTPException(503, "journal_storage_unavailable") from None
    except JournalError as error:
        if error.code in {
            "journal_owner_not_found",
            "journal_not_found",
            "journal_template_not_found",
        }:
            status = 404
        elif error.code.endswith("conflict") or error.code in {
            "journals_disabled",
            "journal_workspace_unavailable",
        }:
            status = 409
        else:
            status = 422
        raise HTTPException(status, error.code) from None


def command(model, body):
    try:
        return model.model_validate(body.model_dump())
    except ValidationError:
        raise HTTPException(422, "journal_invalid_configuration") from None


def build_router(get_read_journals, get_write_journals):
    router = APIRouter(prefix="/api/admin", tags=["administrative-journals"])
    Read = Annotated[AdministerJournals, Depends(get_read_journals)]
    Write = Annotated[AdministerJournals, Depends(get_write_journals)]
    Key = Annotated[UUID, Header(alias="Idempotency-Key")]
    Limit = Annotated[int, Query(ge=1, le=50)]
    Offset = Annotated[int, Query(ge=0, le=100000)]
    mutation = [Depends(require_admin_same_origin)]

    @router.get("/journals/templates", response_model=http.TemplateList)
    async def templates(service: Read):
        values = await respond(service.templates)
        return {"items": [http.Template.model_validate(t.model_dump()) for t in values]}

    @router.get("/users/{owner}/journals", response_model=http.Account)
    async def account(owner: UUID, service: Read, limit: Limit = 20, offset: Offset = 0):
        value = await respond(service.account, owner, limit, offset)
        return {**value, "items": [http.configuration_response(item) for item in value["items"]]}

    @router.post(
        "/users/{owner}/journals/preview-activation",
        response_model=http.Configuration,
        dependencies=mutation,
    )
    async def preview_activation(owner: UUID, body: http.Activation, service: Read):
        return http.configuration_response(
            await respond(service.preview_activation, owner, command(ActivateRun, body))
        )

    @router.post("/users/{owner}/journals", response_model=http.Receipt, dependencies=mutation)
    async def activate(owner: UUID, body: http.Activation, service: Write, key: Key):
        return http.receipt_response(
            await respond(service.activate, owner, command(ActivateRun, body), key)
        )

    @router.get("/users/{owner}/journals/{identifier}", response_model=http.Configuration)
    async def detail(
        owner: UUID,
        identifier: UUID,
        service: Read,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ):
        return http.configuration_response(
            await respond(service.detail, owner, identifier, revision)
        )

    @router.get("/users/{owner}/journals/{identifier}/revisions", response_model=http.History)
    async def history(
        owner: UUID, identifier: UUID, service: Read, limit: Limit = 20, offset: Offset = 0
    ):
        return await respond(service.history, owner, identifier, limit, offset)

    @router.post(
        "/users/{owner}/journals/{identifier}/preview",
        response_model=http.Configuration,
        dependencies=mutation,
    )
    async def preview(owner: UUID, identifier: UUID, body: http.Adjustment, service: Read):
        return http.configuration_response(
            await respond(
                service.preview, owner, identifier, command(AdministrativeAdjustment, body)
            )
        )

    @router.patch(
        "/users/{owner}/journals/{identifier}", response_model=http.Receipt, dependencies=mutation
    )
    async def adjust(
        owner: UUID, identifier: UUID, body: http.Adjustment, service: Write, key: Key
    ):
        return http.receipt_response(
            await respond(
                service.adjust, owner, identifier, command(AdministrativeAdjustment, body), key
            )
        )

    @router.post(
        "/users/{owner}/journals/{identifier}/actions",
        response_model=http.Receipt,
        dependencies=mutation,
    )
    async def lifecycle(
        owner: UUID, identifier: UUID, body: http.Lifecycle, service: Write, key: Key
    ):
        return http.receipt_response(
            await respond(service.lifecycle, owner, identifier, command(ChangeLifecycle, body), key)
        )

    return router
