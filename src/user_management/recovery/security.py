"""Domain-separated credentials and explicit reverse-proxy trust."""

import base64
import hashlib
import hmac
from ipaddress import ip_address, ip_network

from cryptography.fernet import Fernet
from fastapi import Request


class RecoverySecrets:
    def __init__(self, secret: str):
        self.secret = secret.encode()
        self.cipher = Fernet(
            base64.urlsafe_b64encode(
                hmac.digest(self.secret, b"el-espejo/recovery/encryption/v1", "sha256")
            )
        )

    def mac(self, purpose: str, value: str) -> str:
        return hmac.new(self.secret, (purpose + "\0" + value).encode(), hashlib.sha256).hexdigest()

    def email_key(self, email: str) -> str:
        return self.mac("email", email.strip().lower())

    def password_mac(self, user) -> str:
        # Every password change increments session_version. Rehashing the same
        # password during login must not invalidate an otherwise valid code.
        return self.mac("password-version", f"{user.id}:{user.session_version}")


def recovery_client_ip(request: Request, trusted_cidrs: list[str]) -> str:
    networks = [ip_network(cidr) for cidr in trusted_cidrs]
    peer = request.client.host if request.client else "unknown"
    try:
        current = ip_address(peer)
    except ValueError:
        return "unknown"
    if any(current in network for network in networks):
        # Read from the trusted end; arbitrary leftmost forwarded values cannot
        # override the first untrusted address in the chain.
        for candidate in reversed(request.headers.get("x-forwarded-for", "").split(",")):
            if not any(current in network for network in networks):
                break
            try:
                current = ip_address(candidate.strip())
            except ValueError:
                return str(ip_address(peer))
    return str(current.ipv4_mapped or current) if current.version == 6 else str(current)
