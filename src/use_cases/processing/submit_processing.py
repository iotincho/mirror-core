"""Accept originals after their base graph document commits; models stay deferred."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC
from pathlib import Path
from uuid import UUID

from src.core.audio.errors import AudioNoteAlreadyExistsError
from src.core.audio.uploads import validate_audio_upload
from src.core.documents.ports import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    GraphPersistenceError,
)
from src.core.domain.audio_notes import AudioNote
from src.core.domain.documents import Document, NewDocument
from src.core.processing.acceptance import Submissions
from src.core.processing.errors import WorkflowFailure
from src.core.processing.ports import ProcessingWorkspace
from src.core.processing.submissions import SubmissionConflict, fingerprint
from src.core.workspaces.errors import WorkspaceSecretError


def document_identity(document):
    authored = document.authored_at.astimezone(UTC).isoformat() if document.authored_at else None
    return fingerprint(
        {
            "content": document.content,
            "source": document.source,
            "metadata": document.metadata,
            "authored_at": authored,
        }
    )


def imported_document_identity(document):
    # Archive identity also preserves stable ID and creation time. Display titles are derived.
    original = document.model_dump(mode="json", exclude={"title"})
    for name in ("created_at", "authored_at"):
        value = getattr(document, name)
        original[name] = value.astimezone(UTC).isoformat() if value is not None else None
    return fingerprint(original)


def audio_manifest(filename, media_type, content, authored_at):
    return {
        "filename": filename,
        "media_type": media_type,
        "size_bytes": len(content),
        "audio_hash": hashlib.sha256(content).hexdigest(),
        "authored_at": authored_at.astimezone(UTC).isoformat() if authored_at else None,
    }


def audio_metadata(receipt):
    manifest = receipt.manifest
    return AudioNote(
        id=receipt.resource_id,
        filename=manifest["filename"],
        media_type=manifest["media_type"],
        size_bytes=manifest["size_bytes"],
        storage_name=f"{receipt.resource_id}{Path(manifest['filename']).suffix.lower()}",
        created_at=receipt.created_at,
        authored_at=manifest["authored_at"],
        invitation_id=manifest.get("invitation_id"),
        invitation_question_id=manifest.get("invitation_question_id"),
        status="queued",
    )


async def invitation_manifest(
    submissions, owner, operation, key, invitation_id, question_id, *, resource_id=None
):
    if invitation_id is None:
        if question_id is not None:
            raise ValueError("question_requires_invitation")
        return {}
    resolved = await submissions.validate_invitation(owner, invitation_id, question_id)
    previous = await submissions.get(owner, operation, key, resource_id=resource_id)
    if previous is not None and "invitation_question_id" not in previous.manifest:
        # Preserve hashes and originals accepted by v1, including resource-ID aliases.
        if previous.manifest.get("invitation_id") != str(invitation_id):
            raise SubmissionConflict("idempotency_conflict")
        default = await submissions.validate_invitation(owner, invitation_id)
        if resolved != default:
            raise SubmissionConflict("idempotency_conflict")
        return {"invitation_id": str(invitation_id)}
    return {"invitation_id": str(invitation_id), "invitation_question_id": str(resolved)}


class SubmitDocument:
    def __init__(self, submissions: Submissions, runtime: ProcessingWorkspace, *, workflow_config):
        self.workflow_config = workflow_config
        self.submissions, self.runtime = submissions, runtime

    async def execute(
        self,
        document: NewDocument,
        key: UUID,
        *,
        invitation_id: UUID | None = None,
        invitation_question_id: UUID | None = None,
    ):
        if "invitation_id" in document.metadata:
            supplied = UUID(document.metadata["invitation_id"])
            if invitation_id is not None and invitation_id != supplied:
                raise SubmissionConflict("invitation_metadata_conflict")
            invitation_id = supplied
        if "invitation_question_id" in document.metadata:
            supplied = UUID(document.metadata["invitation_question_id"])
            if invitation_question_id is not None and invitation_question_id != supplied:
                raise SubmissionConflict("invitation_metadata_conflict")
            invitation_question_id = supplied
        association = await invitation_manifest(
            self.submissions,
            self.runtime.context.user_id,
            "upload_document",
            key,
            invitation_id,
            invitation_question_id,
            resource_id=document.id,
        )
        if association:
            document = document.model_copy(
                update={
                    "metadata": {
                        **{
                            k: v
                            for k, v in document.metadata.items()
                            if k not in {"invitation_id", "invitation_question_id"}
                        },
                        **association,
                    },
                }
            )
        receipt = await self.submissions.reserve(
            user_id=self.runtime.context.user_id,
            operation="upload_document",
            key=key,
            request_hash=document_identity(document),
            resource_kind="document",
            resource_id=document.id,
            config=self.workflow_config(),
            manifest=association,
        )
        if receipt.accepted_at:
            return (
                await self.runtime.document_store.get(receipt.resource_id),
                await self.submissions.processing.get(receipt.processing_id, receipt.user_id),
            )
        try:
            # Exclude deletion/import while the original and graph are being published.
            async with self.submissions.processing.lock_resource(
                receipt.user_id, receipt.resource_id
            ) as acquired:
                if not acquired:
                    raise SubmissionConflict("processing_active")
                original = Document(
                    **document.model_dump(exclude={"id"}),
                    id=receipt.resource_id,
                    created_at=receipt.created_at,
                )
                try:
                    await self.runtime.document_store.save(original)
                except DocumentAlreadyExistsError:
                    original = await self.runtime.document_store.get(receipt.resource_id)
                    if (
                        document_identity(original) != receipt.request_hash
                        or original.created_at != receipt.created_at
                    ):
                        raise SubmissionConflict("resource_already_exists") from None
                await self.runtime.graph_store.persist_document(original)
                record = await self.submissions.accept(receipt)
                return original, record
        except BaseException:
            # Preserve original and receipt on graph/SQL failure, including ambiguous commits.
            # Reconciliation can also reclaim after the receipt lease expires.
            try:
                await asyncio.shield(self.submissions.release(receipt))
            except Exception:
                pass
            raise


class SubmitAudioNote:
    def __init__(
        self,
        submissions: Submissions,
        runtime: ProcessingWorkspace,
        max_bytes: int,
        *,
        workflow_config,
    ):
        self.workflow_config = workflow_config
        self.submissions, self.runtime, self.max_bytes = submissions, runtime, max_bytes

    async def execute(
        self,
        filename,
        media_type,
        content,
        authored_at,
        key: UUID,
        *,
        invitation_id: UUID | None = None,
        invitation_question_id: UUID | None = None,
    ):
        filename, media_type = validate_audio_upload(filename, media_type, content, self.max_bytes)
        # Validate dates before making a SQL reservation.
        if authored_at is not None and authored_at.tzinfo is None:
            raise ValueError("authored_at must include a timezone")
        manifest = audio_manifest(filename, media_type, content, authored_at)
        manifest.update(
            await invitation_manifest(
                self.submissions,
                self.runtime.context.user_id,
                "upload_audio",
                key,
                invitation_id,
                invitation_question_id,
            )
        )
        receipt = await self.submissions.reserve(
            user_id=self.runtime.context.user_id,
            operation="upload_audio",
            key=key,
            request_hash=fingerprint(manifest),
            resource_kind="audio",
            resource_id=None,
            config=self.workflow_config(),
            manifest=manifest,
        )
        if receipt.accepted_at:
            return (
                await self.runtime.audio_note_store.get(receipt.resource_id),
                await self.submissions.processing.get(receipt.processing_id, receipt.user_id),
            )
        note = audio_metadata(receipt)
        try:
            try:
                await self.runtime.audio_note_store.create(note, content)
            except AudioNoteAlreadyExistsError:
                await verify_audio_original(self.runtime, receipt)
                await self.runtime.audio_note_store.restore_metadata(note)
                note = await self.runtime.audio_note_store.get(note.id)
            record = await self.submissions.accept(receipt)
            return note, record
        except BaseException:
            try:
                await asyncio.shield(self.submissions.release(receipt))
            except Exception:
                pass
            raise


async def verify_audio_original(runtime, receipt):
    note = audio_metadata(receipt)
    await runtime.audio_note_store.verify_original(
        note, size_bytes=receipt.manifest["size_bytes"], sha256=receipt.manifest["audio_hash"]
    )


async def recover_submissions(submissions, runtime_factory, *, report_issue):
    for receipt in await submissions.claim_pending():
        try:
            async with runtime_factory(receipt.user_id) as runtime:
                if receipt.resource_kind == "document":
                    async with submissions.processing.lock_resource(
                        receipt.user_id, receipt.resource_id
                    ) as acquired:
                        if not acquired:
                            continue
                        # Read under the same guard as deletion; never recreate a deleted note.
                        original = await runtime.document_store.get(receipt.resource_id)
                        identity = (
                            (
                                imported_document_identity(original)
                                if receipt.manifest.get("archive_identity") == "original/1"
                                else fingerprint(original.model_dump(mode="json"))
                            )
                            if receipt.operation == "import_document"
                            else document_identity(original)
                        )
                        if identity != receipt.request_hash:
                            raise SubmissionConflict("document_artifact_mismatch")
                        if receipt.operation == "import_document":
                            await submissions.processing.assert_inactive(
                                receipt.user_id, receipt.resource_id
                            )
                        await runtime.graph_store.persist_document(original)
                        await submissions.accept(receipt)
                else:
                    await verify_audio_original(runtime, receipt)
                    await runtime.audio_note_store.restore_metadata(audio_metadata(receipt))
                    await submissions.accept(receipt)
        except GraphPersistenceError as error:
            report_issue(
                "submission_graph_persistence_failed", error, resource_id=str(receipt.resource_id)
            )
            continue
        except (
            OSError,
            DocumentNotFoundError,
            ValueError,
            WorkflowFailure,
            WorkspaceSecretError,
        ):
            # Incomplete uploads remain reserved and retryable with the same key.
            continue
