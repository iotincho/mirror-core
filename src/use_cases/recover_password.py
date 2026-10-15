"""Own short-code recovery, atomic budgets and the password/session transaction."""

import hmac
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi_users.exceptions import InvalidPasswordException
from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import noload

from src.exteriorization.models import InvitationDelivery, PushSubscription
from src.exteriorization.repository import InvitationRepository
from src.processing.models import ProcessingRecord
from src.processing.repository import ProcessingRepository
from src.user_management.models import AccessToken, User
from src.user_management.passwords import validate_password
from src.user_management.recovery.models import RecoveryDelivery
from src.user_management.recovery.repository import RecoveryError, RecoveryRepository
from src.user_management.recovery.security import RecoverySecrets


def recent(times: list, since: datetime) -> list[datetime]:
    return [value for text in times if (value := datetime.fromisoformat(text)) > since]


class RecoverPassword:
    def __init__(self, repository: RecoveryRepository, secrets: RecoverySecrets):
        self.repository, self.secrets = repository, secrets
        self.passwords = PasswordHelper()

    async def limit_ip(self, session, ip: str):
        row = await self.repository.ip(session, self.secrets.mac("ip", ip))
        now = await self.repository.now(session)
        times = recent(row.request_times, now - timedelta(minutes=10))
        if len(times) >= 10:
            wait = max(1, int((times[0] + timedelta(minutes=10) - now).total_seconds()) + 1)
            raise RecoveryError("recovery_rate_limited", 429, wait)
        row.request_times = [value.isoformat() for value in times] + [now.isoformat()]
        row.updated_at = now

    async def user(self, session, email: str, *, lock=False):
        statement = (
            select(User)
            .options(noload(User.oauth_accounts))
            .where(func.lower(User.email) == email.strip().lower())
        )
        if lock:
            statement = statement.with_for_update(of=User, key_share=True)
        return await session.scalar(statement)

    async def request(self, email: str, ip: str) -> None:
        async with self.repository.sessions.begin() as session:
            await self.limit_ip(session, ip)
            address = await self.repository.address(session, self.secrets.email_key(email))
            now = await self.repository.now(session)
            times = recent(address.sent_times, now - timedelta(days=1))
            address.updated_at = now
            if (times and now < times[-1] + timedelta(seconds=60)) or len(times) >= 10:
                return
            if len([value for value in times if value > now - timedelta(hours=1)]) >= 3:
                return
            # Identical address budgets for missing, Google-only and local users.
            # A repeated request does not reveal eligibility through its response.
            user = await self.user(session, email)
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
                address.code_ciphertext = self.secrets.cipher.encrypt(code.encode()).decode()
                address.password_mac = fingerprint
                address.expires_at = now + timedelta(minutes=10)
                address.consumed_at, address.failed_attempts = None, 0
            delivery_id = uuid4()
            record = ProcessingRecord(
                id=uuid4(),
                user_id=user.id,
                workflow="password_recovery_email",
                workflow_version=1,
                resource_kind="auth_email",
                resource_id=delivery_id,
                stage="send",
                config={},
                available_at=now,
            )
            session.add(record)
            await session.flush()
            session.add(
                RecoveryDelivery(
                    id=delivery_id,
                    user_id=user.id,
                    address_key=address.key,
                    challenge_id=address.challenge_id,
                    processing_id=record.id,
                )
            )
            ProcessingRepository.schedule(session, record)

    async def reset(self, email: str, code: str, password: str, ip: str) -> None:
        result = "recovery_invalid_code"
        async with self.repository.sessions.begin() as session:
            await self.limit_ip(session, ip)
            address = await self.repository.address(session, self.secrets.email_key(email))
            now = await self.repository.now(session)
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
                    user = await self.user(session, email, lock=True)
                    if (
                        user is not None
                        and user.id == address.user_id
                        and user.is_active
                        and user.password_login_enabled is True
                        and address.password_mac == self.secrets.password_mac(user)
                    ):
                        try:
                            validate_password(password, user.email)
                        except InvalidPasswordException:
                            result = "recovery_invalid_password"
                        else:
                            user.hashed_password = self.passwords.hash(password)
                            user.session_version += 1
                            address.consumed_at = now
                            address.code_mac = address.code_ciphertext = None
                            await session.execute(
                                delete(AccessToken).where(AccessToken.user_id == user.id)
                            )
                            # Keep the push sender/logout lock order and deactivate
                            # every device attached to any now-revoked session.
                            await InvitationRepository(self.repository.sessions).preference(
                                session, user.id
                            )
                            await session.execute(
                                update(PushSubscription)
                                .where(PushSubscription.user_id == user.id)
                                .values(active=False, updated_at=now)
                            )
                            await session.execute(
                                update(InvitationDelivery)
                                .where(
                                    InvitationDelivery.user_id == user.id,
                                    InvitationDelivery.status.in_(["pending", "retrying"]),
                                )
                                .values(status="cancelled", next_attempt_at=None)
                            )
                            result = "ok"
            # Do not raise inside the transaction: failed attempts and IP budgets
            # must commit even when the submitted code/password is rejected.
        if result != "ok":
            raise RecoveryError(result)
