"""HTTP routes owned by user management."""

from fastapi import APIRouter

from src.adapters.access.api.public.auth.schemas import SessionRead, UserCreate, UserRead
from src.core.auth.identity import AuthenticatedUser


def build_router(fastapi_users, auth_backend, recovery_router, google_oauth, *, cookie_secure):
    router = APIRouter(prefix="/auth", tags=["auth"])
    router.include_router(fastapi_users.get_auth_router(auth_backend))
    router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))
    router.include_router(recovery_router)

    if google_oauth is None:
        return router

    oauth_cookie_options = {
        "csrf_token_cookie_name": "el_espejo_google_oauth_csrf",
        "csrf_token_cookie_path": "/api/auth",
        "csrf_token_cookie_secure": cookie_secure,
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


def session(user: AuthenticatedUser) -> SessionRead:
    return SessionRead(user_id=user.id, email=user.email)
