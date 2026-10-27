"""Verified identity and detached credentials, never an ORM or HTTP schema."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str


@dataclass
class AccountCredentials:
    id: UUID
    email: str
    hashed_password: str = field(repr=False)
    session_version: int = 0
    is_active: bool = True
    password_login_enabled: bool = False


def session_is_current(token_version: int, user_version: int) -> bool:
    return token_version == user_version
