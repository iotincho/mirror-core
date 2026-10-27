"""Bounded Web Push adapter with sanitized outcomes and owned HTTP clients."""

import asyncio
import json
from typing import Any

from src.core.exteriorization.models import PushResult


class WebPushTransport:
    def __init__(self, private_key: str | None, subject: str | None) -> None:
        self.private_key, self.subject = private_key, subject

    async def send(self, subscription: dict, payload: dict, ttl: int) -> PushResult:
        if not (self.private_key and self.subject):
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
                        vapid_private_key=self.private_key,
                        vapid_claims={"sub": self.subject},
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
