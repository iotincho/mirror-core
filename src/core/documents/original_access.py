"""Resolve owner-scoped original documents independently of graph availability."""

from typing import Protocol
from uuid import UUID

from src.core.documents.ports import DocumentStore


class OriginalStorageUnavailable(Exception):
    pass


class OwnerOriginals(Protocol):
    async def documents(self, owner: UUID) -> DocumentStore: ...
