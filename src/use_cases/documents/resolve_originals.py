"""Permit backup export for suspended workspaces without decrypting graph secrets."""

from src.core.documents.original_access import OwnerOriginals
from src.core.workspaces.models import WorkspaceUnavailable
from src.core.workspaces.ports import Workspaces


class ResolveOriginals:
    def __init__(self, workspaces: Workspaces, originals: OwnerOriginals, instance_key: str):
        self.workspaces, self.originals, self.instance_key = workspaces, originals, instance_key

    async def execute(self, owner):
        workspace = await self.workspaces.read(owner)
        if workspace is None or workspace.arcadedb_instance_key != self.instance_key:
            raise WorkspaceUnavailable()
        return await self.originals.documents(owner)
