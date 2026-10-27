"""Recovery state and safe delivery outcomes; no encryption or persistence technology."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class RecoveryError(ValueError):
    def __init__(self, code: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


@dataclass
class RecoveryIP:
    key: str
    request_times: list = field(default_factory=list)
    updated_at: datetime | None = None


@dataclass
class RecoveryAddress:
    key: str
    sent_times: list = field(default_factory=list)
    user_id: UUID | None = None
    challenge_id: UUID | None = None
    code_mac: str | None = field(default=None, repr=False)
    code_ciphertext: str | None = field(default=None, repr=False)
    password_mac: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
    failed_attempts: int = 0
    updated_at: datetime | None = None


@dataclass
class RecoveryDelivery:
    id: UUID
    user_id: UUID
    address_key: str
    challenge_id: UUID
    processing_id: UUID
    status: str = "pending"
    attempts: int = 0
    provider_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class MailResult:
    accepted: bool = False
    retryable: bool = False
    provider_id: str | None = None
    code: str | None = None
    retry_after: float | None = None
