"""Encryption for server-only ArcadeDB credentials."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config import Settings


class WorkspaceSecretError(RuntimeError):
    """Raised when a workspace credential cannot be protected or recovered."""


class WorkspaceSecretCipher:
    """Uses an explicit key or a domain-separated key from the auth secret."""

    def __init__(self, settings: Settings) -> None:
        raw_key = settings.workspace_secret_key
        if raw_key is None:
            if not settings.auth_session_secret:
                raise WorkspaceSecretError("workspace secret encryption is not configured")
            material = hashlib.sha256(
                b"el-espejo/workspace-credential/v1\x00"
                + settings.auth_session_secret.encode()
            ).digest()
            raw_key = base64.urlsafe_b64encode(material).decode()
        try:
            self._fernet = Fernet(raw_key.encode())
        except (TypeError, ValueError) as error:
            raise WorkspaceSecretError("WORKSPACE_SECRET_KEY must be a Fernet key") from error

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as error:
            raise WorkspaceSecretError("workspace credential cannot be decrypted") from error
