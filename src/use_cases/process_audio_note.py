"""Audio owns transcription and document handoff; a child owns graph processing."""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy.exc import SQLAlchemyError

from src.domain.documents import NewDocument, build_document
from src.processing.artifacts import ProcessingArtifacts
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure, WorkflowWaiting
from src.processing.failures import failure_for
from src.services.document_store import DocumentAlreadyExistsError
from src.use_cases.submit_processing import document_identity


class ProcessAudioNote:
    transitions = frozenset({("transcription", "document_creation")})

    def __init__(self, runtime_factory, provider_factory):
        self.runtime_factory, self.provider_factory = runtime_factory, provider_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        record = context.record
        service = "transcription"
        try:
            async with self.runtime_factory(record.user_id) as runtime:
                note = await runtime.audio_note_store.get(record.resource_id)
                if record.stage == "document_processing":
                    child = await context.repository.child(record)
                    if child is None:
                        raise WorkflowFailure("child_processing_missing")
                    if child.status == "failed":
                        await runtime.audio_note_store.save(
                            note.model_copy(
                                update={
                                    "document_error": "document_processing_failed",
                                }
                            )
                        )
                        raise WorkflowFailure(
                            "document_processing_failed", retryable=child.retryable
                        )
                    if child.status != "completed":
                        await context.repository.child_and_wait(record, note.id)
                        raise WorkflowWaiting()
                    await runtime.audio_note_store.save(
                        note.model_copy(update={"document_error": None})
                    )
                    return
                artifacts = ProcessingArtifacts(
                    runtime.context.filesystem_root / "processing" / str(record.id)
                )
                raw = await asyncio.to_thread(runtime.audio_note_store.audio_path(note).read_bytes)
                identity = hashlib.sha256(raw).hexdigest() + ":" + artifacts.digest(record.config)
                if record.stage == "transcription":
                    payload = await artifacts.read("transcript", identity)
                    if payload is None:
                        if note.transcript:
                            # Recover previously transcribed legacy notes without paying again.
                            payload = {
                                "text": note.transcript,
                                "provider": note.transcription_provider or "unknown",
                                "model": note.transcription_model or "unknown",
                            }
                        else:
                            transcriber = self.provider_factory(record.config)
                            await context.assert_lease()
                            await runtime.audio_note_store.save(
                                note.model_copy(
                                    update={
                                        "status": "transcribing",
                                        "error": None,
                                    }
                                )
                            )
                            text = await transcriber.transcribe(
                                runtime.audio_note_store.audio_path(note)
                            )
                            if not text.strip():
                                raise WorkflowFailure("empty_transcription")
                            payload = {
                                "text": text,
                                "provider": transcriber.provider_name,
                                "model": transcriber.model_name,
                            }
                        await context.assert_lease()
                        await artifacts.write("transcript", identity, payload)
                    note = note.model_copy(
                        update={
                            "status": "completed",
                            "transcript": payload["text"],
                            "error": None,
                            "transcription_provider": payload["provider"],
                            "transcription_model": payload["model"],
                        }
                    )
                    await context.assert_lease()
                    await runtime.audio_note_store.save(note)
                    await context.advance(
                        "document_creation", transcript_hash=artifacts.digest(payload)
                    )
                if record.stage == "document_creation":
                    service = "document"
                    if not note.transcript:
                        raise WorkflowFailure("transcript_missing")
                    original = build_document(
                        NewDocument(
                            id=note.id,
                            content=note.transcript,
                            source="pwa_audio",
                            authored_at=note.authored_at,
                            metadata={
                                "audio_note_id": str(note.id),
                                "filename": note.filename,
                                "media_type": note.media_type,
                                "transcription_provider": note.transcription_provider or "unknown",
                                "transcription_model": note.transcription_model or "unknown",
                            },
                        )
                    )
                    await context.assert_lease()
                    try:
                        await runtime.document_store.save(original)
                    except DocumentAlreadyExistsError:
                        existing = await runtime.document_store.get(note.id)
                        if document_identity(existing) != document_identity(original):
                            raise WorkflowFailure("derived_document_conflict") from None
                    await runtime.audio_note_store.save(
                        note.model_copy(
                            update={
                                "document_id": note.id,
                                "document_error": None,
                            }
                        )
                    )
                    await context.repository.child_and_wait(record, note.id)
                    raise WorkflowWaiting()
        except WorkflowFailure as failure:
            await self.project_failure(context, failure, service)
            raise
        except (WorkflowWaiting, LeaseLost, SQLAlchemyError):
            raise
        except Exception as error:
            failure = failure_for(error, record.stage_attempts, service)
            await self.project_failure(context, failure, service)
            raise failure from error

    async def project_failure(self, context, failure, service):
        if service != "transcription":
            return
        try:
            async with self.runtime_factory(context.record.user_id) as runtime:
                note = await runtime.audio_note_store.get(context.record.resource_id)
                await context.assert_lease()
                await runtime.audio_note_store.save(
                    note.model_copy(
                        update={
                            "status": "failed",
                            "error": failure.code,
                        }
                    )
                )
        except Exception:
            pass  # ProcessingRecord is authoritative if the projection is unavailable.
