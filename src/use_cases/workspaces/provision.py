"""Idempotent workspace state transitions coordinated through explicit ports."""

import logging
import secrets
from datetime import UTC, datetime
from uuid import UUID

from src.core.workspaces.errors import WorkspaceSecretError
from src.core.workspaces.models import (
    ProvisioningTarget,
    WorkspaceProvisioningError,
    WorkspaceStatus,
)
from src.core.workspaces.ports import RemoteProvisioning, WorkspaceCipher, Workspaces

logger = logging.getLogger(__name__)


class WorkspaceProvisioner:
    def __init__(
        self,
        store: Workspaces,
        remote: RemoteProvisioning,
        cipher: WorkspaceCipher,
        *,
        instance_key: str,
        schema_version: str,
    ):
        self.store, self.remote, self.cipher = store, remote, cipher
        self.instance_key, self.schema_version = instance_key, schema_version

    async def provision(self, user_id: UUID, *, force: bool = False):
        target, workspace = await self._start(user_id, force=force)
        if target is None:
            return workspace
        try:
            await self._provision_remote(target)
        except (WorkspaceProvisioningError, WorkspaceSecretError) as error:
            logger.warning("workspace_provisioning_failed user_id=%s", user_id, exc_info=True)
            return await self._fail(user_id, code="arcadedb_provisioning_failed", detail=str(error))
        except Exception:
            logger.exception("workspace_provisioning_failed user_id=%s", user_id)
            return await self._fail(
                user_id,
                code="workspace_provisioning_failed",
                detail="Unexpected workspace provisioning failure",
            )
        async with self.store.transaction() as transaction:
            workspace = await self._required(transaction, user_id)
            now = datetime.now(UTC)
            workspace.status = WorkspaceStatus.ACTIVE
            workspace.schema_version = self.schema_version
            workspace.provisioned_at = workspace.updated_at = now
            workspace.last_error_code = workspace.last_error = None
            return workspace

    async def _start(self, user_id, *, force):
        async with self.store.transaction() as transaction:
            workspace = await transaction.get_or_create(
                user_id,
                arcadedb_instance_key=self.instance_key,
                graph_secret_ciphertext=self.cipher.encrypt(secrets.token_urlsafe(32)),
            )
            if (
                workspace.status in {WorkspaceStatus.ACTIVE, WorkspaceStatus.PROVISIONING}
                and not force
            ):
                return None, workspace
            if workspace.status == WorkspaceStatus.SUSPENDED:
                return None, workspace
            workspace.status = WorkspaceStatus.PROVISIONING
            workspace.last_error_code = workspace.last_error = None
            workspace.updated_at = datetime.now(UTC)
            return ProvisioningTarget(
                workspace.user_id,
                workspace.database_name,
                workspace.graph_username,
                workspace.graph_secret_ciphertext,
            ), workspace

    async def _provision_remote(self, target):
        secret = self.cipher.decrypt(target.graph_secret_ciphertext)
        await self.remote.provision(target, secret)

    async def _fail(self, user_id, *, code, detail):
        async with self.store.transaction() as transaction:
            workspace = await self._required(transaction, user_id)
            workspace.status = WorkspaceStatus.FAILED
            workspace.updated_at = datetime.now(UTC)
            workspace.last_error_code, workspace.last_error = code, detail[:500]
            return workspace

    @staticmethod
    async def _required(transaction, user_id):
        workspace = await transaction.get(user_id, for_update=True)
        if workspace is None:
            raise RuntimeError("workspace disappeared during provisioning")
        return workspace


class ReconcileWorkspaces:
    def __init__(self, store: Workspaces, provisioner: WorkspaceProvisioner):
        self.store, self.provisioner = store, provisioner

    async def execute(self):
        for user_id in await self.store.active_user_ids():
            await self.provisioner.provision(user_id, force=True)
