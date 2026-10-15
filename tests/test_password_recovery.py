"""Provider and trusted-proxy contracts without external network calls."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import Request

from src.config import Settings
from src.user_management.recovery.resend import ResendMailTransport
from src.user_management.recovery.security import RecoverySecrets, recovery_client_ip


@pytest.fixture
def anyio_backend():
    return "asyncio"


def request(peer, forwarded=""):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/forgot-password",
            "client": (peer, 1234),
            "headers": [(b"x-forwarded-for", forwarded.encode())],
        }
    )


def test_proxy_headers_are_ignored_until_the_socket_peer_is_trusted():
    assert recovery_client_ip(request("203.0.113.1", "192.0.2.1"), []) == "203.0.113.1"
    assert (
        recovery_client_ip(request("203.0.113.1", "192.0.2.1"), ["172.18.0.0/16"]) == "203.0.113.1"
    )
    assert (
        recovery_client_ip(
            request("172.18.0.2", "192.0.2.99, 203.0.113.4, 172.18.0.3"), ["172.18.0.0/16"]
        )
        == "203.0.113.4"
    )
    assert recovery_client_ip(request("172.18.0.2", "bad-ip"), ["172.18.0.0/16"]) == "172.18.0.2"
    assert recovery_client_ip(request("::ffff:192.0.2.1"), []) == "192.0.2.1"


@pytest.mark.parametrize("network", ["0.0.0.0/0", "::/0", "not-a-network"])
def test_proxy_configuration_rejects_unbounded_or_invalid_trust(network):
    with pytest.raises(ValidationError):
        Settings(password_recovery_trusted_proxy_cidrs=[network])


def test_credential_mac_is_domain_separated_and_payload_is_encrypted():
    secrets = RecoverySecrets("a-stable-separate-recovery-test-secret")
    assert secrets.email_key(" Alice@Example.com ") == secrets.email_key("alice@example.com")
    assert secrets.mac("email", "123456") != secrets.mac("code", "123456")
    encrypted = secrets.cipher.encrypt(b"012345")
    assert b"012345" not in encrypted
    assert secrets.cipher.decrypt(encrypted) == b"012345"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,retryable", [(400, False), (401, False), (422, False), (429, True), (500, True)]
)
async def test_resend_classifies_errors_without_leaking_body(status, retryable):
    async def provider(request):
        return httpx.Response(status, json={"message": "private provider detail"})

    mail = ResendMailTransport(
        "private-key", "access@example.com", transport=httpx.MockTransport(provider)
    )
    result = await mail.send("user@example.com", "012345", "delivery-id", datetime.now(UTC))
    assert not result.accepted and result.retryable == retryable
    assert "private" not in str(result)


@pytest.mark.anyio
async def test_resend_payload_has_plain_code_no_link_and_stable_idempotency_key():
    payloads = []

    async def provider(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Idempotency-Key"] == "password-recovery/one-delivery"
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "provider-id"})

    mail = ResendMailTransport(
        "test-key", "El Espejo <access@example.com>", transport=httpx.MockTransport(provider)
    )
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    for _ in range(2):
        result = await mail.send("user@example.com", "012345", "one-delivery", expiry)
        assert result.accepted and result.provider_id == "provider-id"
    assert payloads[0] == payloads[1]
    assert "012345" in payloads[0]["text"] and "012345" in payloads[0]["html"]
    assert "https://" not in payloads[0]["text"]


@pytest.mark.anyio
async def test_ambiguous_provider_timeout_is_retryable():
    async def provider(request):
        raise httpx.ReadTimeout("private timeout", request=request)

    mail = ResendMailTransport(
        "test-key", "access@example.com", transport=httpx.MockTransport(provider)
    )
    result = await mail.send("user@example.com", "012345", "delivery-id", datetime.now(UTC))
    assert result.retryable and result.code == "resend_unavailable"
