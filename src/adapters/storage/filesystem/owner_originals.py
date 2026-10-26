"""Checked access to original documents; no graph credentials or provisioning."""

import asyncio

from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.core.documents.original_access import OriginalStorageUnavailable


class FileOwnerOriginals:
    def __init__(self, root):
        self.root = root

    async def documents(self, owner):
        directory = self.root / str(owner) / "documents"

        def checked():
            root = directory.parent
            if root.is_symlink() or directory.is_symlink() or any(
                p.is_symlink() for p in directory.glob("*")
            ):
                raise OriginalStorageUnavailable()
            return FileDocumentStore(directory)

        return await asyncio.to_thread(checked)
