"""Accept originals quickly; no model or graph calls run in the request."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC
from pathlib import Path
from uuid import UUID

from src.config import get_settings
from src.domain.audio_notes import AudioNote
from src.domain.documents import Document, NewDocument
from src.extractors.document_embeddings import EMBEDDINGS_PROFILE, EmbeddingConfiguration
from src.extractors.emotions import EMOTIONS_PROFILE
from src.processing.execution import WorkflowFailure
from src.processing.submissions import SubmissionConflict, SubmissionRepository, fingerprint
from src.services.audio_note_store import AudioNoteAlreadyExistsError
from src.services.document_store import DocumentAlreadyExistsError, DocumentNotFoundError
from src.use_cases.create_audio_note import validate_audio_upload
from src.workspaces.secrets import WorkspaceSecretError


def workflow_config():
    settings = get_settings()
    return {
        "transcription_model": settings.openai_transcription_model,
        "document_workflow_version": 4,
        "extractors": [
            {
                "name": "emotions",
                "profile": EMOTIONS_PROFILE.model_dump(mode="json"),
                "provider": settings.llm_provider,
                "model": settings.openai_model,
            },
            {
                "name": "document_embeddings",
                "profile": EMBEDDINGS_PROFILE.model_dump(mode="json"),
                "configuration": EmbeddingConfiguration(
                    model=settings.openai_embedding_model,
                    dimensions=settings.openai_embedding_dimensions,
                    segmentation_model=settings.openai_model or "unconfigured",
                    segmentation_threshold=settings.embedding_segmentation_threshold,
                    section_max_tokens=settings.embedding_section_max_tokens,
                    section_target_tokens=settings.embedding_section_target_tokens,
                ).model_dump(mode="json"),
                "force": False,
            },
        ],
    }


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
        status="queued",
    )


class SubmitDocument:
    def __init__(self, submissions: SubmissionRepository, runtime):
        self.submissions, self.runtime = submissions, runtime

    async def execute(self, document: NewDocument, key: UUID):
        receipt = await self.submissions.reserve(
            user_id=self.runtime.context.user_id,
            operation="upload_document",
            key=key,
            request_hash=document_identity(document),
            resource_kind="document",
            resource_id=document.id,
            config=workflow_config(),
            manifest={},
        )
        if receipt.accepted_at:
            return (
                await self.runtime.document_store.get(receipt.resource_id),
                await self.submissions.processing.get(receipt.processing_id, receipt.user_id),
            )
        try:
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
            record = await self.submissions.accept(receipt)
            return original, record
        except BaseException:
            # Preserve both original and receipt if SQL fails after the file write.
            # Reconciliation can also reclaim after the receipt lease expires.
            try:
                await asyncio.shield(self.submissions.release(receipt))
            except Exception:
                pass
            raise


class SubmitAudioNote:
    def __init__(self, submissions: SubmissionRepository, runtime, max_bytes: int):
        self.submissions, self.runtime, self.max_bytes = submissions, runtime, max_bytes

    async def execute(self, filename, media_type, content, authored_at, key: UUID):
        filename, media_type = validate_audio_upload(filename, media_type, content, self.max_bytes)
        # Validate dates before making a SQL reservation.
        if authored_at is not None and authored_at.tzinfo is None:
            raise ValueError("authored_at must include a timezone")
        manifest = audio_manifest(filename, media_type, content, authored_at)
        receipt = await self.submissions.reserve(
            user_id=self.runtime.context.user_id,
            operation="upload_audio",
            key=key,
            request_hash=fingerprint(manifest),
            resource_kind="audio",
            resource_id=None,
            config=workflow_config(),
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
    raw = await asyncio.to_thread(runtime.audio_note_store.audio_path(note).read_bytes)
    if (
        len(raw) != receipt.manifest["size_bytes"]
        or hashlib.sha256(raw).hexdigest() != receipt.manifest["audio_hash"]
    ):
        raise SubmissionConflict("audio_artifact_mismatch")


async def recover_submissions(submissions, runtime_factory):
    for receipt in await submissions.claim_pending():
        try:
            async with runtime_factory(receipt.user_id) as runtime:
                if receipt.resource_kind == "document":
                    original = await runtime.document_store.get(receipt.resource_id)
                    if document_identity(original) != receipt.request_hash:
                        raise SubmissionConflict("document_artifact_mismatch")
                else:
                    await verify_audio_original(runtime, receipt)
                    await runtime.audio_note_store.restore_metadata(audio_metadata(receipt))
                await submissions.accept(receipt)
        except (OSError, DocumentNotFoundError, ValueError, WorkflowFailure, WorkspaceSecretError):
            # Incomplete uploads remain reserved and retryable with the same key.
            continue
