"""Stable inbox cursors, onboarding copy and domain errors."""

import base64
import json
from datetime import datetime
from uuid import UUID


class NotificationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


ONBOARDING = (
    (
        "first-note",
        "Dale lugar a tu primera reflexión",
        "Escribí o grabá algo, a tu manera.",
        "No hace falta encontrar las palabras perfectas. Una idea o unos segundos de voz alcanzan.",
        "open_capture",
    ),
    (
        "install",
        "Tu espacio, más cerca",
        "Instalá El Espejo en este dispositivo.",
        "Podés agregar El Espejo a tu pantalla de inicio. "
        "Es opcional y podés hacerlo cuando quieras.",
        "open_install_help",
    ),
    (
        "daily",
        "Una pregunta para encontrar por dónde empezar",
        "Elegí si querés una pregunta diaria.",
        "La pregunta estará en la app. "
        "Si querés, también podés recibir un aviso en este dispositivo.",
        "open_invitation_settings",
    ),
)


def encode_cursor(item):
    return base64.urlsafe_b64encode(
        json.dumps([item.read_at is None, item.published_at.isoformat(), str(item.id)]).encode()
    ).decode()


def decode_cursor(cursor):
    try:
        if len(cursor) > 300:
            raise ValueError()
        raw = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or not isinstance(raw[0], bool)
            or not all(isinstance(item, str) for item in raw[1:])
        ):
            raise ValueError()
        unread, when, identifier = raw
        when = datetime.fromisoformat(when)
        if when.tzinfo is None:
            raise ValueError()
        return unread, when, UUID(identifier)
    except (ValueError, TypeError, KeyError):
        raise NotificationError("invalid_notification_cursor") from None
