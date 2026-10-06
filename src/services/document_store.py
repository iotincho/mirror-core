"""Durable storage port and local filesystem adapter for Documents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from src.domain.documents import Document
from src.services.durable_files import sync_published


class DocumentAlreadyExistsError(Exception):
    """Raised when a caller retries with an already persisted stable ID."""


class DocumentNotFoundError(Exception):
    """Raised when a requested original document does not exist."""


class DocumentStore(Protocol):
    """Persistence boundary used by document use cases."""

    async def save(self, document: Document) -> None:
        """Persist one original document."""

    async def update_title(self, document_id: object, title: str) -> Document:
        """Update only the display title, preserving the original material."""

    async def list(self) -> list[Document]: ...

    async def delete(self, document_id: object) -> None: ...

    async def get(self, document_id: object) -> Document:
        """Retrieve one original document by its stable ID."""


class FileDocumentStore:
    """Store each original document in a separate, auditable JSON file."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def save(self, document: Document) -> None:
        return await asyncio.to_thread(self._save, document)

    async def update_title(self, document_id: object, title: str) -> Document:
        return await asyncio.to_thread(self._update_title, document_id, title)

    async def list(self) -> list[Document]:
        return await asyncio.to_thread(self._list)

    async def delete(self, document_id: object) -> None:
        return await asyncio.to_thread(self._delete, document_id)

    async def get(self, document_id: object) -> Document:
        return await asyncio.to_thread(self._get, document_id)

    def _save(self, document: Document) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        destination = self._directory / f"{document.id}.json"
        if destination.exists():
            raise DocumentAlreadyExistsError(f"Document {document.id} already exists")

        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            # Exclusive publication: concurrent submissions cannot replace the original.
            try:
                destination.hardlink_to(temporary)
                sync_published(destination)
            except FileExistsError as error:
                raise DocumentAlreadyExistsError(
                    f"Document {document.id} already exists"
                ) from error
        finally:
            temporary.unlink(missing_ok=True)

    def _update_title(self, document_id: object, title: str) -> Document:
        document = self._get(document_id)
        updated = Document.model_validate({**document.model_dump(), "title": title})
        destination = self._directory / f"{document.id}.json"
        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(updated.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        sync_published(destination)
        return updated

    def _list(self) -> list[Document]:
        if not self._directory.exists():
            return []
        return sorted(
            (
                Document.model_validate_json(path.read_text(encoding="utf-8"))
                for path in self._directory.glob("*.json")
            ),
            key=lambda document: document.created_at,
            reverse=True,
        )

    def _delete(self, document_id: object) -> None:
        destination = self._directory / f"{document_id}.json"
        if not destination.is_file():
            raise DocumentNotFoundError(f"Document {document_id} was not found")
        destination.unlink()

    def _get(self, document_id: object) -> Document:
        destination = self._directory / f"{document_id}.json"
        if not destination.is_file():
            raise DocumentNotFoundError(f"Document {document_id} was not found")
        return Document.model_validate_json(destination.read_text(encoding="utf-8"))
