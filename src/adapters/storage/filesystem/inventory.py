"""Read metadata locally; reject symlinks, oversized originals and identity mismatches."""

import asyncio
from pathlib import Path

from src.core.administration.inventory import OriginalMetadata


def read_metadata(directory: Path):
    if directory.is_symlink():
        raise ValueError("symlink_directory")
    if not directory.exists():
        return None
    result = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("invalid_original")
        data = OriginalMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        if path.stem != str(data.id):
            raise ValueError("original_identity_mismatch")
        result.append(data)
    return result


class FileInventory:
    def __init__(self, root):
        self.root = Path(root)

    async def list(self, user_id):
        def read():
            if not self.root.is_dir() or self.root.is_symlink():
                raise ValueError("workspaces_root_unavailable")
            directory = self.root / str(user_id) / "documents"
            if directory.parent.is_symlink():
                raise ValueError("symlink_workspace")
            return read_metadata(directory)

        return await asyncio.to_thread(read)
