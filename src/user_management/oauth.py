"""Optional OAuth clients owned by the user-management module."""

from __future__ import annotations

from dataclasses import dataclass

from httpx_oauth.clients.google import GoogleOAuth2

from src.config import Settings


@dataclass(frozen=True)
class GoogleOAuthConfiguration:
    client: GoogleOAuth2
    redirect_url: str
    state_secret: str


def get_google_oauth_configuration(settings: Settings) -> GoogleOAuthConfiguration | None:
    """Return Google OAuth only when its complete, server-side configuration exists."""
    state_secret = settings.google_oauth_state_secret or settings.auth_session_secret
    if not all(
        (
            settings.google_oauth_client_id,
            settings.google_oauth_client_secret,
            settings.google_oauth_redirect_url,
            state_secret,
        )
    ):
        return None
    return GoogleOAuthConfiguration(
        client=GoogleOAuth2(
            settings.google_oauth_client_id,
            settings.google_oauth_client_secret,
        ),
        redirect_url=settings.google_oauth_redirect_url,
        state_secret=state_secret,
    )
