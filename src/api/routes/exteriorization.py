"""Authenticated invitation endpoints. Public path is prefixed by /api."""

from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.api.schemas.exteriorization import (
    InvitationRead,
    PreferenceRead,
    PreferenceUpdate,
    SubscriptionCreate,
    SubscriptionRead,
    TestInvitationRequest,
)
from src.config import get_settings
from src.exteriorization.dependencies import get_invitations, require_push_configuration
from src.exteriorization.models import Invitation, InvitationPreference, PushSubscription
from src.exteriorization.repository import session_fingerprint
from src.exteriorization.web_push import validate_subscription
from src.use_cases.configure_invitations import ConfigureInvitations
from src.user_management.authentication import COOKIE_NAME
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user


async def require_same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "cross_origin_request")
    if origin:
        parsed = urlsplit(origin)
        allowed = get_settings().web_push_allowed_origins
        if origin not in allowed and (
            parsed.scheme != request.url.scheme or parsed.netloc != request.url.netloc
        ):
            raise HTTPException(403, "cross_origin_request")
    # SameSite=Strict + JSON bodies/custom idempotency header protect requests
    # without Origin (native clients). No credentialed CORS is enabled.


router = APIRouter(
    prefix="/exteriorization",
    tags=["exteriorization"],
    dependencies=[Depends(require_same_origin)],
)
User = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
Service = Annotated[ConfigureInvitations, Depends(get_invitations)]


def fingerprint(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Authentication required")
    return session_fingerprint(token)


@router.get("/preferences", response_model=PreferenceRead)
async def preferences(user: User, service: Service) -> InvitationPreference:
    return await service.preferences(user.id)


@router.put("/preferences", response_model=PreferenceRead)
async def configure(
    payload: PreferenceUpdate,
    user: User,
    service: Service,
) -> InvitationPreference:
    return await service.configure(user.id, payload.enabled, payload.local_time, payload.timezone)


@router.get("/push/public-key")
async def public_key(user: User) -> dict[str, str]:
    require_push_configuration()
    return {"public_key": get_settings().web_push_public_key}


@router.post("/push/subscriptions", response_model=SubscriptionRead)
async def subscribe(
    payload: SubscriptionCreate,
    request: Request,
    user: User,
    service: Service,
) -> PushSubscription:
    require_push_configuration()
    validate_subscription(
        payload.endpoint,
        payload.keys.p256dh,
        payload.keys.auth,
        get_settings().web_push_allowed_hosts,
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
    require_push_configuration()
    return await service.test(user.id, fingerprint(request), payload.subscription_id, key)


@router.get("/invitations/{invitation_id}", response_model=InvitationRead)
async def invitation(invitation_id: UUID, user: User, service: Service) -> Invitation:
    return await service.get_invitation(user.id, invitation_id)


@router.post("/invitations/{invitation_id}/opened", response_model=InvitationRead)
async def opened(invitation_id: UUID, user: User, service: Service) -> Invitation:
    return await service.open_invitation(user.id, invitation_id)
