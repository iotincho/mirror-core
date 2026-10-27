"""Bounded Resend HTTP adapter; never expose provider responses or credentials."""

import math
from html import escape

import httpx

from src.core.auth.recovery import MailResult


class ResendMailTransport:
    def __init__(self, api_key: str, sender: str, *, transport=None):
        self.api_key, self.sender, self.transport = api_key, sender, transport

    async def send(self, email: str, code: str, delivery_id: str, expires_at) -> MailResult:
        text = (
            f"Tu código de recuperación de El Espejo es: {code}\n\n"
            f"Vence a las {expires_at:%H:%M UTC} y se puede usar una sola vez.\n"
            "Si no pediste recuperar tu contraseña, podés ignorar este email."
        )
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Idempotency-Key": f"password-recovery/{delivery_id}",
                    },
                    json={
                        "from": self.sender,
                        "to": [email],
                        "subject": "Tu código para recuperar el acceso a El Espejo",
                        "text": text,
                        "html": '<div style="font-family:system-ui;max-width:480px;padding:24px">'
                        '<h1 style="font-size:24px">Recuperá tu acceso</h1>'
                        "<p>Ingresá este código en El Espejo:</p>"
                        '<p style="font-size:32px;letter-spacing:8px;font-weight:700">'
                        f"{escape(code)}</p>"
                        f"<p>Vence a las {expires_at:%H:%M UTC}. Usalo una sola vez.</p>"
                        "<p>Si no lo solicitaste, podés ignorar este email.</p></div>",
                    },
                )
        except httpx.HTTPError:
            return MailResult(retryable=True, code="resend_unavailable")
        if response.is_success:
            try:
                identifier = response.json()["id"]
                if not isinstance(identifier, str) or len(identifier) > 100:
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                return MailResult(retryable=True, code="resend_invalid_response")
            return MailResult(accepted=True, provider_id=identifier)
        retry_after = None
        try:
            seconds = float(response.headers.get("Retry-After", ""))
            if math.isfinite(seconds) and seconds > 0:
                retry_after = seconds
        except ValueError:
            pass
        return MailResult(
            retryable=response.status_code in {409, 429} or response.status_code >= 500,
            code="resend_temporary_error"
            if response.status_code in {409, 429} or response.status_code >= 500
            else "resend_rejected",
            retry_after=retry_after,
        )
