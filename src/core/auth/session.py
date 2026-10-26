"""Detached session facts for short-lived authorization checks."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class SessionOwner:
    id: UUID
    workspace_status: str | None
    instance_key: str | None


class SessionLookup(Protocol):
    async def lookup(self, token: str) -> SessionOwner | None: ...


class SessionExpired(Exception):
    pass
