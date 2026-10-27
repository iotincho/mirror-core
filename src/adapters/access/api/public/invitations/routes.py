"""Public invitation routes; translate requests to owner-scoped application actions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.adapters.access.api.public.auth.cookies import COOKIE_NAME
from src.adapters.access.api.public.invitations.schemas import (
    InvitationRead,
    PreferenceRead,
    PreferenceUpdate,
    SubscriptionCreate,
    SubscriptionRead,
    TestInvitationRequest,
)
from src.core.auth.identity import AuthenticatedUser
from src.core.exteriorization.models import (
    Invitation,
    InvitationPreference,
    PushSubscription,
    session_fingerprint,
)
from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations


def fingerprint(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Authentication required")
    return session_fingerprint(token)


def build_router(get_authenticated_user, get_invitations, require_same_origin):
    router = APIRouter(
        prefix="/exteriorization",
        tags=["exteriorization"],
        dependencies=[Depends(require_same_origin)],
    )
    User = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
    Service = Annotated[ConfigureInvitations, Depends(get_invitations)]

    @router.get("/preferences", response_model=PreferenceRead)
    async def preferences(user: User, service: Service) -> InvitationPreference:
        return await service.preferences(user.id)

    @router.put("/preferences", response_model=PreferenceRead)
    async def configure(
        payload: PreferenceUpdate,
        user: User,
        service: Service,
    ) -> InvitationPreference:
        return await service.configure(
            user.id, payload.enabled, payload.local_time, payload.timezone
        )

    @router.get("/push/public-key")
    async def public_key(user: User, service: Service) -> dict[str, str]:
        return {"public_key": service.public_key()}

    @router.post("/push/subscriptions", response_model=SubscriptionRead)
    async def subscribe(
        payload: SubscriptionCreate,
        request: Request,
        user: User,
        service: Service,
    ) -> PushSubscription:
        service.validate_push_subscription(
            payload.endpoint,
            payload.keys.p256dh,
            payload.keys.auth,
        )
        return await service.subscribe(
            user.id,
            fingerprint(request),
            payload.endpoint,
            payload.keys.p256dh,
            payload.keys.auth,
        )

    @router.delete("/push/subscriptions/{subscription_id}", status_code=204)
    async def unsubscribe(
        subscription_id: UUID,
        request: Request,
        user: User,
        service: Service,
    ) -> None:
        await service.unsubscribe(user.id, fingerprint(request), subscription_id)

    @router.post("/invitations/test", response_model=InvitationRead, status_code=202)
    async def test_invitation(
        payload: TestInvitationRequest,
        request: Request,
        user: User,
        service: Service,
        key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> Invitation:
        service.public_key()
        return await service.test(user.id, fingerprint(request), payload.subscription_id, key)

    @router.get("/invitations/{invitation_id}", response_model=InvitationRead)
    async def invitation(invitation_id: UUID, user: User, service: Service) -> Invitation:
        return await service.get_invitation(user.id, invitation_id)

    @router.post("/invitations/{invitation_id}/opened", response_model=InvitationRead)
    async def opened(invitation_id: UUID, user: User, service: Service) -> Invitation:
        return await service.open_invitation(user.id, invitation_id)

    return router
