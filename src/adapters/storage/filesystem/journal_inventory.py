"""Read metadata one original at a time; never open binary audio or graph stores."""

import asyncio
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from src.core.journals.contracts import EntryReference
from src.core.journals.errors import JournalStorageUnavailable
from src.core.journals.inventory import OriginalEntry, count_originals


class OriginalMetadata(BaseModel):
    id: UUID
    metadata: dict[str, str] = Field(default_factory=dict)
    journal_reference: EntryReference | None = None
    document_id: UUID | None = None


class FileJournalInventory:
    def __init__(self, root: Path):
        self.root = root

    async def counts(self, owner: UUID):
        def read():
            workspace = self.root / str(owner)
            try:
                if self.root.is_symlink() or workspace.is_symlink() or not workspace.is_dir():
                    raise ValueError("workspace_unavailable")
                return count_originals(
                    self._entries(workspace / "audio-notes", "audio"),
                    self._entries(workspace / "documents", "document"),
                )
            except (OSError, ValueError):
                raise JournalStorageUnavailable() from None

        return await asyncio.to_thread(read)

    @staticmethod
    def _entries(directory, kind):
        if directory.is_symlink():
            raise ValueError("invalid_original_directory")
        for path in directory.glob("*.json"):
            if path.is_symlink():
                raise ValueError("invalid_original")
            item = OriginalMetadata.model_validate_json(path.read_text(encoding="utf-8"))
            if str(item.id) != path.stem:
                raise ValueError("original_identity_mismatch")
            reference = item.journal_reference
            if reference is None and "journal_reference" in item.metadata:
                reference = EntryReference.model_validate_json(item.metadata["journal_reference"])
            yield OriginalEntry(
                kind, item.id, reference.run_id if reference else None,
                (UUID(item.metadata["audio_note_id"])
                 if item.metadata.get("audio_note_id") else None),
                item.document_id,
            )
