"""Domain-separated credentials and explicit reverse-proxy trust."""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet


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


    def encrypt_code(self, code: str) -> str:
        return self.cipher.encrypt(code.encode()).decode()

    def decrypt_code(self, ciphertext: str) -> str:
        return self.cipher.decrypt(ciphertext.encode()).decode()
