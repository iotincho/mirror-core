"""Revocable cookie authentication backed by PostgreSQL."""

from uuid import UUID

from fastapi import Depends
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy

from src.config import get_settings
from src.user_management.database import get_access_token_db
from src.user_management.models import AccessToken, User

COOKIE_NAME = "el_espejo_session"

_settings = get_settings()
cookie_transport = CookieTransport(
    cookie_name=COOKIE_NAME,
    cookie_max_age=_settings.auth_session_ttl_seconds,
    cookie_secure=_settings.auth_cookie_secure,
    cookie_httponly=True,
    cookie_samesite="strict",
)


def get_database_strategy(
    access_token_db: AccessTokenDatabase[AccessToken] = Depends(get_access_token_db),
) -> DatabaseStrategy[User, UUID, AccessToken]:
    return DatabaseStrategy(
        access_token_db,
        lifetime_seconds=get_settings().auth_session_ttl_seconds,
    )


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
