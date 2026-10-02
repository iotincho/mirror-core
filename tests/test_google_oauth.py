from fastapi import FastAPI

from src.config import Settings
from src.user_management.oauth import get_google_oauth_configuration
from src.user_management.routes import build_router


def google_settings(**values: object) -> Settings:
    return Settings(
        auth_session_secret="auth-session-secret",
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret="google-client-secret",
        google_oauth_redirect_url="https://app.example.test/oauth/google/callback",
        **values,
    )


def route_paths(settings: Settings) -> set[str]:
    app = FastAPI()
    app.include_router(build_router(settings))
    return set(app.openapi()["paths"])


def test_google_oauth_stays_disabled_without_a_complete_configuration() -> None:
    settings = Settings(auth_session_secret="auth-session-secret")

    assert get_google_oauth_configuration(settings) is None
    assert "/auth/google/authorize" not in route_paths(settings)


def test_google_oauth_registers_login_and_explicit_association_routes() -> None:
    paths = route_paths(google_settings())

    assert {
        "/auth/google/authorize",
        "/auth/google/callback",
        "/auth/associate/google/authorize",
        "/auth/associate/google/callback",
    } <= paths


def test_google_oauth_uses_a_dedicated_state_secret_when_configured() -> None:
    configuration = get_google_oauth_configuration(
        google_settings(google_oauth_state_secret="google-state-secret")
    )

    assert configuration is not None
    assert configuration.redirect_url == "https://app.example.test/oauth/google/callback"
    assert configuration.state_secret == "google-state-secret"
