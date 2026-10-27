"""Original storage and base graph projection boundaries."""

from typing import Protocol

from src.core.domain.documents import Document


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


class GraphPersistenceError(RuntimeError):
    """A document projection could not be verified."""


class DocumentProjection(Protocol):
    async def persist_document(self, document: Document) -> None: ...
