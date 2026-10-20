"""Portable originals, independent of graph identities and extraction results."""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.documents import Document
from src.processing.submissions import SubmissionConflict, SubmissionRepository, fingerprint
from src.services.document_store import DocumentAlreadyExistsError, DocumentNotFoundError
from src.use_cases.submit_processing import imported_document_identity, workflow_config


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
    def __init__(self, documents, processing=None, user_id=None, submissions=None, *, graph=None):
        self.documents = documents
        self.processing, self.user_id = processing, user_id
        self.submissions = submissions
        self.graph = graph

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
        if imported_document_identity(current) != imported_document_identity(document):
            raise ArchiveConflict(f"El documento {document.id} ya existe con datos distintos.")
        return True

    async def import_archive(self, archive):
        if self.graph is None:
            raise RuntimeError("Document import requires a graph store")
        # Check every conflict before writing the first document. Recheck under the
        # resource lock as concurrent imports/deletions can race with this preflight.
        for document in archive.documents:
            await self.existing(document)
        created = existing = 0
        for document in archive.documents:
            async with self.processing.lock_resource(self.user_id, document.id) as acquired:
                if not acquired:
                    raise ArchiveConflict("Hay un documento en procesamiento; reintentá luego.")
                present = await self.existing(document)
                submissions = self.submissions or SubmissionRepository(self.processing)
                request_hash = imported_document_identity(document)
                previous = await submissions.get(self.user_id, "import_document", document.id)
                if previous is not None:
                    if previous.manifest.get("archive_identity") == "original/1":
                        if previous.request_hash != request_hash:
                            raise SubmissionConflict("idempotency_conflict")
                    elif not present and previous.request_hash != fingerprint(
                        document.model_dump(mode="json")
                    ):
                        raise SubmissionConflict("idempotency_conflict")
                    # Existing immutable material was checked above under the resource lock.
                    # Keep legacy receipts replayable after a derived title changes.
                    request_hash = previous.request_hash
                receipt = await submissions.accepted(
                    self.user_id, "import_document", document.id, request_hash
                )
                if receipt is not None:
                    if not present:
                        raise ArchiveConflict(
                            "El original de un documento importado no está disponible."
                        )
                    existing += 1
                    continue
                try:
                    await self.processing.assert_inactive(self.user_id, document.id)
                except ValueError as error:
                    raise ArchiveConflict(
                        "Hay un documento en procesamiento; reintentá luego."
                    ) from error
                receipt = await submissions.reserve(
                    user_id=self.user_id,
                    operation="import_document",
                    key=document.id,
                    request_hash=request_hash,
                    resource_kind="document",
                    resource_id=document.id,
                    config=workflow_config(),
                    manifest={"archive_identity": "original/1"},
                )
                if receipt.accepted_at is None:
                    try:
                        if not present:
                            try:
                                await self.documents.save(Document(**document.model_dump()))
                            except DocumentAlreadyExistsError:
                                present = await self.existing(document)
                        original = await self.documents.get(document.id)
                        await self.graph.persist_document(original)
                        # The receipt, processing record and outbox make extraction
                        # recoverable even if the HTTP request or broker fails.
                        await submissions.accept(receipt)
                    except BaseException:
                        try:
                            await asyncio.shield(submissions.release(receipt))
                        except Exception:
                            pass
                        raise
                existing += int(present)
                created += int(not present)
        return {"imported": created, "existing": existing, "total": len(archive.documents)}
