"""Temporary manifests composed with the existing immutable artifact stores."""

import asyncio
import shutil
from uuid import UUID, uuid5

from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts


class PreviewStore:
    def __init__(self, workspace_root, preview_id):
        self.id = UUID(str(preview_id))
        self.root = workspace_root / "laboratory" / "previews" / str(self.id)
        self.manifest = ProcessingArtifacts(self.root)
        self.layers = LayerArtifacts(self.root / "layers")

    def run_id(self, document_id):
        return uuid5(self.id, f"document:{document_id}")

    async def read(self, name):
        return await self.manifest.read(name, str(self.id))

    async def write(self, name, value):
        await self.manifest.write(name, str(self.id), value)

    async def delete(self):
        await asyncio.to_thread(shutil.rmtree, self.root, True)


class PreviewFiles:
    def __init__(self, root):
        self._root = root

    def for_preview(self, preview_id):
        return PreviewStore(self._root, preview_id)
