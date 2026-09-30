"""HTTP routes owned by user management."""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.config import Settings, get_settings
from src.user_management.authentication import auth_backend
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user
from src.user_management.oauth import get_google_oauth_configuration
from src.user_management.schemas import SessionRead, UserCreate, UserRead
from src.user_management.users import fastapi_users


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])
    router.include_router(fastapi_users.get_auth_router(auth_backend))
    router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))

    google_oauth = get_google_oauth_configuration(settings)
    if google_oauth is None:
        return router

    oauth_cookie_options = {
        "csrf_token_cookie_name": "el_espejo_google_oauth_csrf",
        "csrf_token_cookie_path": "/api/auth",
        "csrf_token_cookie_secure": settings.auth_cookie_secure,
        "csrf_token_cookie_httponly": True,
        "csrf_token_cookie_samesite": "lax",
    }
    router.include_router(
        fastapi_users.get_oauth_router(
            google_oauth.client,
            auth_backend,
            google_oauth.state_secret,
            redirect_url=google_oauth.redirect_url,
            associate_by_email=False,
            **oauth_cookie_options,
        ),
        prefix="/google",
    )
    associate_cookie_options = {
        **oauth_cookie_options,
        "csrf_token_cookie_name": "el_espejo_google_associate_csrf",
    }
    router.include_router(
        fastapi_users.get_oauth_associate_router(
            google_oauth.client,
            UserRead,
            google_oauth.state_secret,
            redirect_url=google_oauth.redirect_url,
            **associate_cookie_options,
        ),
        prefix="/associate/google",
    )
    return router


router = build_router(get_settings())


@router.get("/session", response_model=SessionRead)
def session(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> SessionRead:
    return SessionRead(user_id=user.id, email=user.email)
