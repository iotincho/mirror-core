"""Idempotent retry/re-extraction requests, separate from worker execution."""

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.processing.configuration import document_workflow_version
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.processing.submissions import SubmissionConflict, fingerprint
from src.services.document_store import DocumentNotFoundError
from src.use_cases.submit_processing import workflow_config


class RequestProcessing:
    def __init__(self, repository, runtime):
        self.repository, self.runtime = repository, runtime
        self.changed = False

    async def mutate(self, operation, key, request, resource_id, action, lock=True, branch_id=None):
        owner = self.runtime.context.user_id
        async with self.repository.sessions() as session:
            previous = await session.scalar(
                select(ProcessingReceipt).where(
                    ProcessingReceipt.user_id == owner,
                    ProcessingReceipt.operation == operation,
                    ProcessingReceipt.key == key,
                )
            )
            if previous:
                if previous.request_hash != fingerprint(request):
                    raise SubmissionConflict("idempotency_conflict")
                if previous.accepted_at:
                    record = await session.get(ProcessingRecord, previous.processing_id)
                    if record.resource_deleted:
                        raise SubmissionConflict("resource_deleted")
                    return record

        @asynccontextmanager
        async def guard():
            if lock:
                manager = (
                    self.repository.lock_extractor(owner, resource_id, branch_id)
                    if branch_id
                    else self.repository.lock_resource(owner, resource_id)
                )
                async with manager as acquired:
                    yield acquired
            else:
                yield True

        async with guard() as locked:
            if not locked:
                raise SubmissionConflict("processing_active")
            async with self.repository.sessions.begin() as session:
                now = await session.scalar(select(func.clock_timestamp()))
                identifier = uuid4()
                await session.execute(
                    insert(ProcessingReceipt)
                    .values(
                        id=identifier,
                        user_id=owner,
                        operation=operation,
                        key=key,
                        request_hash=fingerprint(request),
                        resource_kind="document",
                        resource_id=resource_id,
                        config={},
                        manifest={},
                        lease_token=uuid4(),
                        lease_expires_at=now + timedelta(seconds=90),
                        created_at=now,
                    )
                    .on_conflict_do_nothing()
                )
                receipt = await session.scalar(
                    select(ProcessingReceipt)
                    .where(
                        ProcessingReceipt.user_id == owner,
                        ProcessingReceipt.operation == operation,
                        ProcessingReceipt.key == key,
                    )
                    .with_for_update()
                )
                if receipt.request_hash != fingerprint(request):
                    raise SubmissionConflict("idempotency_conflict")
                if receipt.accepted_at:
                    return await session.get(ProcessingRecord, receipt.processing_id)
                record = await action(session, now)
                receipt.processing_id, receipt.accepted_at = record.id, now
        return record

    async def reprocess_document(self, document_id: UUID, key: UUID):
        await self.runtime.document_store.get(document_id)
        config = workflow_config()

        async def action(session, now):
            await self.repository.assert_inactive(self.runtime.context.user_id, document_id)
            record = ProcessingRecord(
                id=uuid4(),
                user_id=self.runtime.context.user_id,
                workflow="document",
                resource_kind="document",
                resource_id=document_id,
                document_id=document_id,
                workflow_version=document_workflow_version(config),
                stage="document_persistence",
                config=config,
            )
            session.add(record)
            await session.flush()
            self.repository.event(session, record)
            self.repository.schedule(session, record)
            return record

        return await self.mutate(
            "persist_document",
            key,
            {"document_id": str(document_id)},
            document_id,
            action,
        )

    async def retry(self, processing_id: UUID, key: UUID):
        record = await self.repository.get(processing_id, self.runtime.context.user_id)
        if record is None:
            raise DocumentNotFoundError("Processing not found")
        lock = record.status == "failed"

        async def action(session, now):
            current = await session.get(ProcessingRecord, record.id, with_for_update=True)
            if current.resource_deleted:
                raise SubmissionConflict("resource_deleted")
            if current.status != "failed":
                return current
            if not lock:
                raise SubmissionConflict("processing_state_changed")
            await self.retry_record(session, current, now)
            await self.resume_ancestors(session, current, now)
            return current

        return await self.mutate(
            "retry",
            key,
            {"processing_id": str(processing_id)},
            record.resource_id,
            action,
            lock=lock,
            branch_id=record.id if record.workflow == "extractor" else None,
        )

    async def retry_record(self, session, current, now):
        """Resume only retryable failed descendants; completed siblings stay untouched."""
        if current.resource_deleted:
            raise SubmissionConflict("resource_deleted")
        if current.workflow == "document" and current.workflow_version == 1:
            current.workflow_version = 2
            current.stage = "document_persistence"
            current.config = workflow_config()
            current.checkpoints = {}
            current.extraction_run_id = None
            current.retryable = True
        children = []
        if current.workflow == "document" and current.workflow_version == 4:
            children = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(
                            ProcessingRecord.parent_processing_id == current.id,
                            ProcessingRecord.user_id == current.user_id,
                            ProcessingRecord.workflow == "extractor",
                        )
                        .with_for_update()
                    )
                ).all()
            )
        elif current.child_processing_id:
            child = await session.get(
                ProcessingRecord, current.child_processing_id, with_for_update=True
            )
            if child is not None:
                children = [child]
        legacy_child = any(
            child.workflow == "document"
            and child.workflow_version == 1
            and child.status == "failed"
            for child in children
        )
        if not current.retryable and not legacy_child:
            raise SubmissionConflict("processing_not_retryable")
        if children:
            restarted = False
            for child in children:
                if child.resource_deleted:
                    raise SubmissionConflict("resource_deleted")
                if child.status == "failed" and (
                    child.retryable
                    or (child.workflow == "document" and child.workflow_version == 1)
                ):
                    await self.retry_record(session, child, now)
                    restarted = True
            if not restarted and all(child.status == "failed" for child in children):
                raise SubmissionConflict("processing_not_retryable")
            self.wait(session, current, now)
            for child in children:
                if child.status in {"completed", "failed"}:
                    await self.repository.wake_parent(session, child, now)
        else:
            if current.resource_kind == "document":
                await self.runtime.document_store.get(current.resource_id)
            else:
                await self.runtime.audio_note_store.get(current.resource_id)
            if current.workflow != "extractor":
                await self.repository.assert_inactive(
                    current.user_id,
                    current.resource_id,
                    exclude=[current.id]
                    + ([current.parent_processing_id] if current.parent_processing_id else []),
                )
            self.reset(session, current, now)

    def wait(self, session, record, now):
        self.changed = True
        record.status = "waiting"
        record.stage_attempts = 0
        record.error_code = None
        record.retryable = False
        record.completed_at = None
        record.version += 1
        record.updated_at = now
        self.repository.event(session, record)

    async def resume_ancestors(self, session, record, now):
        parent_id = record.parent_processing_id
        while parent_id:
            parent = await session.get(ProcessingRecord, parent_id, with_for_update=True)
            if parent is None or parent.user_id != record.user_id or parent.resource_deleted:
                raise SubmissionConflict("resource_deleted")
            if parent.status == "failed":
                self.wait(session, parent, now)
            parent_id = parent.parent_processing_id

    def reset(self, session, current, now):
        self.changed = True
        current.status = "queued"
        current.generation += 1
        current.version += 1
        current.fencing_token += 1
        current.stage_attempts = 0
        current.error_code = None
        current.retryable = False
        current.available_at = current.updated_at = now
        current.completed_at = None
        self.repository.event(session, current)
        self.repository.schedule(session, current)

    async def recover_audio(self, audio_note_id, key):
        current = await self.repository.latest(self.runtime.context.user_id, audio_note_id, "audio")
        if current is not None:
            return await self.retry(current.id, key)
        note = await self.runtime.audio_note_store.get(audio_note_id)
        if note.status != "completed" or not note.transcript:
            raise SubmissionConflict("transcription_incomplete")

        async def action(session, now):
            await self.repository.assert_inactive(self.runtime.context.user_id, note.id)
            record = ProcessingRecord(
                id=uuid4(),
                user_id=self.runtime.context.user_id,
                workflow="audio",
                resource_kind="audio",
                resource_id=note.id,
                workflow_version=2,
                stage="document_creation",
                config=workflow_config(),
            )
            session.add(record)
            await session.flush()
            self.repository.event(session, record)
            self.repository.schedule(session, record)
            self.changed = True
            return record

        return await self.mutate(
            "recover_audio", key, {"audio_note_id": str(note.id)}, note.id, action
        )
