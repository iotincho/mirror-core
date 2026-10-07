"""Portable originals, independent of graph identities and extraction results."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.documents import Document
from src.services.document_store import DocumentAlreadyExistsError, DocumentNotFoundError


class ArchivedDocument(Document):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("content", "source")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Document text and source must not be blank")
        return value

    @field_validator("created_at", "authored_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Dates must include timezone")
        return value


class DocumentArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["el-espejo-documents"] = "el-espejo-documents"
    version: Literal[1] = 1
    exported_at: datetime
    documents: list[ArchivedDocument] = Field(max_length=10000)

    @field_validator("documents")
    @classmethod
    def unique_ids(cls, values):
        if len({item.id for item in values}) != len(values):
            raise ValueError("Duplicate document IDs")
        return values


class ArchiveConflict(ValueError):
    pass


class DocumentArchiveTransfer:
    def __init__(self, documents, graph=None, processing=None, user_id=None):
        self.documents, self.graph = documents, graph
        self.processing, self.user_id = processing, user_id

    async def export(self):
        return DocumentArchive(
            exported_at=datetime.now(UTC),
            documents=[ArchivedDocument(**doc.model_dump()) for doc in await self.documents.list()],
        )

    async def existing(self, document):
        try:
            current = await self.documents.get(document.id)
        except DocumentNotFoundError:
            return False
        if current.model_dump() != document.model_dump():
            raise ArchiveConflict(f"El documento {document.id} ya existe con datos distintos.")
        return True

    async def import_archive(self, archive):
        # Check every conflict before writing the first document. Recheck under the
        # resource lock as concurrent imports/deletions can race with this preflight.
        for document in archive.documents:
            await self.existing(document)
        created = existing = 0
        for document in archive.documents:
            async with self.processing.lock_resource(self.user_id, document.id) as acquired:
                if not acquired:
                    raise ArchiveConflict("Hay un documento en procesamiento; reintentá luego.")
                try:
                    await self.processing.assert_inactive(self.user_id, document.id)
                except ValueError as error:
                    raise ArchiveConflict(
                        "Hay un documento en procesamiento; reintentá luego."
                    ) from error
                present = await self.existing(document)
                if not present:
                    try:
                        await self.documents.save(Document(**document.model_dump()))
                    except DocumentAlreadyExistsError:
                        present = await self.existing(document)
                # Even when already saved, repair a graph write interrupted on a
                # previous attempt. Report success only once both stores agree.
                await self.graph.persist_document(document)
                existing += int(present)
                created += int(not present)
        return {"imported": created, "existing": existing, "total": len(archive.documents)}
