"""Workspace persistence, credential protection and isolated remote provisioning."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from src.core.workspaces.models import ProvisioningTarget, Workspace


class WorkspaceTransaction(Protocol):
    async def get(self, user_id: UUID, *, for_update: bool = False) -> Workspace | None: ...
    async def get_or_create(
        self, user_id: UUID, *, arcadedb_instance_key: str, graph_secret_ciphertext: str
    ) -> Workspace: ...


class Workspaces(Protocol):
    async def read(self, user_id: UUID) -> Workspace | None: ...
    async def active_user_ids(self) -> list[UUID]: ...
    def transaction(self) -> AbstractAsyncContextManager[WorkspaceTransaction]: ...


class WorkspaceCipher(Protocol):
    def encrypt(self, value: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class RemoteProvisioning(Protocol):
    async def provision(self, target: ProvisioningTarget, secret: str) -> None: ...
