"""Resolve only the verified owner, preserving setup states and suspension."""

from src.core.workspaces.errors import WorkspaceSecretError
from src.core.workspaces.models import ResolvedWorkspace, WorkspaceStatus, WorkspaceUnavailable
from src.core.workspaces.ports import WorkspaceCipher, Workspaces


class WorkspaceAccess:
    def __init__(
        self, store: Workspaces, cipher: WorkspaceCipher, instance_key: str, provisioner=None
    ):
        self.store, self.cipher, self.instance_key = store, cipher, instance_key
        self.provisioner = provisioner

    def setup_status(self, workspace):
        if workspace is None:
            return "unavailable"
        if workspace.status == WorkspaceStatus.ACTIVE:
            try:
                self._resolve(workspace)
            except WorkspaceUnavailable:
                return "unavailable"
        return workspace.status

    async def status(self, user_id):
        return self.setup_status(await self.store.read(user_id))

    async def prepare(self, user_id):
        workspace = await self.store.read(user_id)
        if workspace is not None and workspace.status in {
            WorkspaceStatus.ACTIVE,
            WorkspaceStatus.PROVISIONING,
            WorkspaceStatus.SUSPENDED,
        }:
            return self.setup_status(workspace)
        return self.setup_status(await self.provisioner.provision(user_id))

    async def resolve(self, user_id):
        return self._resolve(await self.store.read(user_id))

    def _resolve(self, workspace):
        if workspace is None:
            raise WorkspaceUnavailable()
        if workspace.status != WorkspaceStatus.ACTIVE:
            raise WorkspaceUnavailable("Personal workspace is preparing")
        if workspace.arcadedb_instance_key != self.instance_key:
            raise WorkspaceUnavailable()
        try:
            secret = self.cipher.decrypt(workspace.graph_secret_ciphertext)
        except WorkspaceSecretError as error:
            raise WorkspaceUnavailable() from error
        return ResolvedWorkspace(workspace, secret)
