"""Compose FastAPI Users around application password policy and verified identities."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport

from src.adapters.access.api.public.auth.authentication import (
    InvitationDatabaseStrategy as Strategy,
)
from src.adapters.access.api.public.auth.manager import UserManager as Manager
from src.adapters.access.api.public.auth.routes import build_router as auth_router
from src.adapters.access.api.public.auth.routes import session as read_session
from src.adapters.access.api.public.auth.schemas import SessionRead
from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.authentication import PostgresAuthentication
from src.bootstrap.database import get_access_token_db, get_user_db
from src.bootstrap.oauth import get_google_oauth_configuration
from src.bootstrap.recovery import router as recovery_router
from src.config import get_settings
from src.core.auth.identity import AuthenticatedUser as AuthenticatedUser
from src.use_cases.auth.authenticate import AuthenticateUser

COOKIE_NAME = "el_espejo_session"


def UserManager(user_db, token_secret):
    async def authenticate(credentials, passwords):
        adapter = PostgresAuthentication(user_db)
        result = await AuthenticateUser(adapter, passwords).execute(
            credentials.username,
            credentials.password,
        )
        return adapter.user if result is not None else None

    async def registered(user_id):
        from src.bootstrap.workspaces import provision_workspace_for_user

        return await provision_workspace_for_user(user_id)

    return Manager(user_db, token_secret, authenticate=authenticate, on_registered=registered)


async def get_user_manager(user_db=Depends(get_user_db)):
    secret = get_settings().auth_session_secret
    if not secret:
        raise HTTPException(503, detail="Authentication is not configured")
    yield UserManager(user_db, secret)


def InvitationDatabaseStrategy(database, lifetime_seconds):
    async def deactivate_session(user_id, token):
        from src.exteriorization.dependencies import get_invitation_repository
        from src.exteriorization.repository import session_fingerprint

        await get_invitation_repository().deactivate_session(user_id, session_fingerprint(token))

    return Strategy(database, lifetime_seconds, deactivate_session=deactivate_session)


def get_database_strategy(access_token_db=Depends(get_access_token_db)):
    return InvitationDatabaseStrategy(
        access_token_db,
        lifetime_seconds=get_settings().auth_session_ttl_seconds,
    )


_settings = get_settings()
cookie_transport = CookieTransport(
    cookie_name=COOKIE_NAME,
    cookie_max_age=_settings.auth_session_ttl_seconds,
    cookie_secure=_settings.auth_cookie_secure,
    cookie_httponly=True,
    cookie_samesite="strict",
)
auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True)


def get_authenticated_user(
    user: Annotated[User, Depends(current_active_user)],
) -> AuthenticatedUser:
    return AuthenticatedUser(id=user.id, email=user.email)


require_authenticated = get_authenticated_user


def session(user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)]) -> SessionRead:
    return read_session(user)


def build_router(settings):
    return auth_router(
        fastapi_users,
        auth_backend,
        recovery_router,
        get_google_oauth_configuration(settings),
        cookie_secure=settings.auth_cookie_secure,
    )


router = build_router(_settings)
router.add_api_route("/session", session, methods=["GET"], response_model=SessionRead)
