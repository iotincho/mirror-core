"""Own short-code recovery, atomic budgets and the password/session transaction."""

import hmac
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from src.core.auth.passwords import InvalidPassword, validate_password
from src.core.auth.ports import Passwords, RecoverySecrets, RecoveryStore
from src.core.auth.recovery import RecoveryError


def recent(times: list, since: datetime) -> list[datetime]:
    return [value for text in times if (value := datetime.fromisoformat(text)) > since]


class RecoverPassword:
    def __init__(self, repository: RecoveryStore, secrets: RecoverySecrets, passwords: Passwords):
        self.repository, self.secrets = repository, secrets
        self.passwords = passwords

    async def limit_ip(self, transaction, ip: str):
        row = await transaction.ip(self.secrets.mac("ip", ip))
        now = await transaction.now()
        times = recent(row.request_times, now - timedelta(minutes=10))
        if len(times) >= 10:
            wait = max(1, int((times[0] + timedelta(minutes=10) - now).total_seconds()) + 1)
            raise RecoveryError("recovery_rate_limited", retry_after=wait)
        row.request_times = [value.isoformat() for value in times] + [now.isoformat()]
        row.updated_at = now

    async def request(self, email: str, ip: str) -> None:
        async with self.repository.transaction() as transaction:
            await self.limit_ip(transaction, ip)
            address = await transaction.address(self.secrets.email_key(email))
            now = await transaction.now()
            times = recent(address.sent_times, now - timedelta(days=1))
            address.updated_at = now
            if (times and now < times[-1] + timedelta(seconds=60)) or len(times) >= 10:
                return
            if len([value for value in times if value > now - timedelta(hours=1)]) >= 3:
                return
            # Identical address budgets for missing, Google-only and local users.
            # A repeated request does not reveal eligibility through its response.
            user = await transaction.user(email)
            address.sent_times = [value.isoformat() for value in times] + [now.isoformat()]
            if user is None or not user.is_active or user.password_login_enabled is not True:
                return
            fingerprint = self.secrets.password_mac(user)
            current = (
                address.user_id == user.id
                and address.expires_at is not None
                and address.expires_at > now
                and address.consumed_at is None
                and address.password_mac == fingerprint
            )
            if current and address.failed_attempts >= 5:
                return  # Re-requesting cannot reset an exhausted challenge's attempts.
            if not current:
                code = f"{secrets.randbelow(1_000_000):06d}"
                address.user_id, address.challenge_id = user.id, uuid4()
                address.code_mac = self.secrets.mac("code", f"{address.challenge_id}:{code}")
                address.code_ciphertext = self.secrets.encrypt_code(code)
                address.password_mac = fingerprint
                address.expires_at = now + timedelta(minutes=10)
                address.consumed_at, address.failed_attempts = None, 0
            delivery_id = uuid4()
            await transaction.enqueue_email(
                delivery_id, uuid4(), user.id, address.key, address.challenge_id, now
            )

    async def reset(self, email: str, code: str, password: str, ip: str) -> None:
        result = "recovery_invalid_code"
        async with self.repository.transaction() as transaction:
            await self.limit_ip(transaction, ip)
            address = await transaction.address(self.secrets.email_key(email))
            now = await transaction.now()
            address.updated_at = now
            if (
                address.code_mac is not None
                and address.consumed_at is None
                and address.expires_at is not None
                and now < address.expires_at
                and address.failed_attempts < 5
            ):
                expected = self.secrets.mac("code", f"{address.challenge_id}:{code}")
                if not hmac.compare_digest(address.code_mac, expected):
                    address.failed_attempts += 1
                    if address.failed_attempts >= 5:
                        address.code_ciphertext = address.code_mac = None
                else:
                    user = await transaction.user(email, lock=True)
                    if (
                        user is not None
                        and user.id == address.user_id
                        and user.is_active
                        and user.password_login_enabled is True
                        and address.password_mac == self.secrets.password_mac(user)
                    ):
                        try:
                            validate_password(password, user.email)
                        except InvalidPassword:
                            result = "recovery_invalid_password"
                        else:
                            user.hashed_password = self.passwords.hash(password)
                            user.session_version += 1
                            address.consumed_at = now
                            address.code_mac = address.code_ciphertext = None
                            # Preserve session/push revocation and their lock order in
                            # the same transaction as consuming the code/password.
                            await transaction.revoke_access(user.id, now)
                            result = "ok"
            # Do not raise inside the transaction: failed attempts and IP budgets
            # must commit even when the submitted code/password is rejected.
        if result != "ok":
            raise RecoveryError(result)
