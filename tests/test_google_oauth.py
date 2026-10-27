import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from httpx_oauth.clients.google import GoogleOAuth2

from src.adapters.access.api.public.request_logging import RequestLoggingMiddleware
from src.bootstrap.auth import build_router
from src.bootstrap.oauth import get_google_oauth_configuration
from src.bootstrap.public_api import app as public_app
from src.bootstrap.settings import Settings


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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body,provider_status,expected_status,expected_code",
    [
        ({"error": "invalid_grant"}, 400, 400, "invalid_grant"),
        ({"error": "invalid_client"}, 401, 502, "invalid_client"),
        ({"error": "private-provider-value"}, 400, 502, "unknown"),
        ({"error": {"private": "provider"}}, 400, 502, "unknown"),
        ("not-json-private", 503, 502, "unknown"),
    ],
)
async def test_google_token_rejection_is_safe_and_correlated(
    monkeypatch, caplog, body, provider_status, expected_status, expected_code,
):
    requests = []

    def provider(request):
        requests.append(request)
        if isinstance(body, dict):
            return httpx.Response(provider_status, json={
                **body, "error_description": "private-provider-description",
            })
        return httpx.Response(provider_status, text=body)

    monkeypatch.setattr(GoogleOAuth2, "get_httpx_client", lambda self: httpx.AsyncClient(
        transport=httpx.MockTransport(provider),
    ))
    app = FastAPI(exception_handlers=public_app.exception_handlers.copy())
    app.include_router(build_router(google_settings()))
    app.add_middleware(RequestLoggingMiddleware)
    # httpx INFO logs contain request URLs, so inspect application logs separately.
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://app.example.test",
        ) as client:
            response = await client.get("/auth/google/callback", params={
                "code": "private-authorization-code", "state": "private-state",
            })
    assert response.status_code == expected_status
    assert response.json() == {"detail": (
        "oauth_authorization_invalid" if expected_status == 400 else "oauth_unavailable"
    )}
    assert len(requests) == 1
    assert parse_qs(requests[0].content.decode())["redirect_uri"] == [
        "https://app.example.test/oauth/google/callback",
    ]
    assert f"provider_error={expected_code}" in caplog.text
    assert f"request_id={response.headers['X-Request-ID']}" in caplog.text
    assert "private-" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["", "?error=access_denied&state=synthetic"])
async def test_missing_or_denied_google_authorization_is_controlled(query, caplog):
    app = FastAPI(exception_handlers=public_app.exception_handlers.copy())
    app.include_router(build_router(google_settings()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://app.example.test",
    ) as client:
        response = await client.get(f"/auth/google/callback{query}")
    assert response.status_code == 400
    assert response.json() == {"detail": "oauth_authorization_invalid"}
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.anyio
async def test_authorization_uses_the_same_public_pwa_redirect_as_token_exchange():
    app = FastAPI()
    app.include_router(build_router(google_settings()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://app.example.test",
    ) as client:
        response = await client.get("/auth/google/authorize")
    assert response.status_code == 200
    parameters = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert parameters["redirect_uri"] == ["https://app.example.test/oauth/google/callback"]
