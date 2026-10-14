"""Web Push boundary. Provider responses and subscription secrets never escape."""

import asyncio
import base64
import ipaddress
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey

from src.config import Settings
from src.exteriorization.repository import InvitationError


@dataclass(frozen=True)
class PushResult:
    accepted: bool = False
    expired: bool = False
    retryable: bool = False
    code: str | None = None


class PushTransport(Protocol):
    async def send(self, subscription: dict, payload: dict, ttl: int) -> PushResult: ...


def validate_subscription(endpoint: str, p256dh: str, auth: str, allowed_hosts: list[str]) -> None:
    try:
        url = urlsplit(endpoint)
        hostname = (url.hostname or "").lower()
        if (
            url.scheme != "https"
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.fragment
            or not hostname
            or not any(hostname == host or hostname.endswith("." + host) for host in allowed_hosts)
        ):
            raise ValueError
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError
        key = base64.urlsafe_b64decode(p256dh + "=" * (-len(p256dh) % 4))
        secret = base64.urlsafe_b64decode(auth + "=" * (-len(auth) % 4))
        EllipticCurvePublicKey.from_encoded_point(SECP256R1(), key)
        if len(secret) != 16:
            raise ValueError
    except (ValueError, TypeError):
        raise InvitationError("invalid_push_subscription") from None


class WebPushTransport:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, subscription: dict, payload: dict, ttl: int) -> PushResult:
        if not (self.settings.web_push_private_key and self.settings.web_push_subject):
            return PushResult(code="web_push_not_configured")

        # Copy claims per request: the library may add provider-specific audience/expiry.
        def execute() -> PushResult:
            from pywebpush import WebPushException, webpush
            from requests import Response, Session

            class PushSession(Session):
                def post(self, *args: Any, **kwargs: Any) -> Response:
                    kwargs["allow_redirects"] = False
                    return super().post(*args, **kwargs)

            try:
                with PushSession() as http:
                    webpush(
                        subscription_info=subscription,
                        data=json.dumps(payload, ensure_ascii=False),
                        vapid_private_key=self.settings.web_push_private_key,
                        vapid_claims={"sub": self.settings.web_push_subject},
                        ttl=ttl,
                        timeout=15,
                        requests_session=http,
                    )
                return PushResult(accepted=True)
            except WebPushException as error:
                status = getattr(error.response, "status_code", None)
                if status in (404, 410):
                    return PushResult(expired=True, code="push_subscription_expired")
                if status in (408, 429) or (status is not None and status >= 500):
                    return PushResult(retryable=True, code="push_transient_error")
                return PushResult(code="push_rejected")
            except Exception:
                # Never propagate exceptions that can carry endpoints or VAPID headers.
                return PushResult(retryable=True, code="push_transport_unavailable")

        return await asyncio.to_thread(execute)
