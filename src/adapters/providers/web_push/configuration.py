"""Validate allowed provider destinations and cryptographic subscription material."""

import base64
import ipaddress
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey

from src.core.exteriorization.models import InvitationError


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


class PushConfiguration:
    def __init__(self, public_key, private_key, subject, allowed_hosts):
        self.key, self.private_key, self.subject = public_key, private_key, subject
        self.allowed_hosts = allowed_hosts

    def public_key(self):
        if not (self.key and self.private_key and self.subject):
            raise InvitationError("web_push_not_configured")
        return self.key

    def validate(self, endpoint, p256dh, auth):
        self.public_key()
        validate_subscription(endpoint, p256dh, auth, self.allowed_hosts)
