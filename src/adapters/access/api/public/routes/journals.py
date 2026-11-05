"""Public journals: session-owned reads and intention edits only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from src.adapters.access.api.public.schemas import journals as http
from src.core.auth.identity import AuthenticatedUser
from src.core.journals.contracts import EditIntention
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals


async def invoke(operation):
    try:
        return await operation
    except JournalStorageUnavailable:
        raise HTTPException(503, "journal_storage_unavailable") from None
    except JournalError as error:
        status = (
            404
            if error.code in {"journal_not_found", "journal_owner_not_found"}
            else (403 if error.code == "journal_workspace_unavailable" else 409)
        )
        raise HTTPException(status, error.code) from None


def build_router(get_user, get_queries, get_management, require_same_origin):
    router = APIRouter(
        prefix="/journals", tags=["journals"], dependencies=[Depends(require_same_origin)]
    )
    User = Annotated[AuthenticatedUser, Depends(get_user)]
    Queries = Annotated[QueryJournals, Depends(get_queries)]
    Management = Annotated[ManageJournals, Depends(get_management)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0, le=100000)]

    @router.get("", response_model=http.RunPage)
    async def runs(user: User, service: Queries, limit: Limit = 30, offset: Offset = 0):
        return await invoke(service.list(user.id, limit=limit, offset=offset))

    @router.get("/active", response_model=http.ActiveRun)
    async def active(user: User, service: Queries):
        return await invoke(service.active(user.id))

    @router.get("/{run_id}", response_model=http.RunRead)
    async def detail(
        run_id: UUID,
        user: User,
        service: Queries,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ):
        return await invoke(service.public(user.id, run_id, revision))

    @router.get("/{run_id}/entries", response_model=http.EntryPage)
    async def entries(
        run_id: UUID, user: User, service: Queries, limit: Limit = 30, offset: Offset = 0
    ):
        return await invoke(service.entries(user.id, run_id, limit=limit, offset=offset))

    @router.get("/{run_id}/question", response_model=http.CurrentQuestion)
    async def question(run_id: UUID, user: User, service: Queries):
        return await invoke(service.latest_invitation(user.id, run_id))

    @router.get("/{run_id}/intention", response_model=http.IntentionState)
    async def intention(run_id: UUID, user: User, service: Queries):
        return await invoke(service.intention_state(user.id, run_id))

    @router.get("/{run_id}/intention/versions", response_model=http.IntentionPage)
    async def versions(
        run_id: UUID, user: User, service: Queries, limit: Limit = 20, offset: Offset = 0
    ):
        return await invoke(service.intentions(user.id, run_id, limit=limit, offset=offset))

    @router.put("/{run_id}/intention", response_model=http.MutationRead)
    async def edit(
        run_id: UUID,
        body: http.IntentionEdit,
        user: User,
        service: Management,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        receipt = await invoke(
            service.edit_intention(user.id, run_id, EditIntention(**body.model_dump()), key)
        )
        return http.MutationRead(
            key=receipt.key,
            run_id=receipt.run_id,
            revision=receipt.revision,
            recorded_at=receipt.recorded_at,
        )

    return router
