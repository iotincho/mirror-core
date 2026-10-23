"""Compatibility imports; canonical implementation: src.core.documents.ports."""

from src.adapters.storage.filesystem.documents import FileDocumentStore as FileDocumentStore
from src.core.documents.ports import DocumentAlreadyExistsError as DocumentAlreadyExistsError
from src.core.documents.ports import DocumentNotFoundError as DocumentNotFoundError
from src.core.documents.ports import DocumentStore as DocumentStore
from src.core.domain.documents import Document as Document
