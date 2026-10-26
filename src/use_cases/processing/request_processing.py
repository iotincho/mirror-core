"""Idempotent retry/re-extraction requests, separate from worker execution."""

from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import UUID, uuid4

from src.core.documents.ports import DocumentNotFoundError
from src.core.processing.configuration import document_workflow_version
from src.core.processing.models import ProcessingJob
from src.core.processing.ports import ProcessingWorkspace
from src.core.processing.retry import reset_job
from src.core.processing.submissions import SubmissionConflict, fingerprint
from src.core.processing.transactions import ProcessingRequests


class RequestProcessing:
    def __init__(
        self, repository: ProcessingRequests, runtime: ProcessingWorkspace, *, workflow_config
    ):
        self.repository, self.runtime = repository, runtime
        self.workflow_config = workflow_config
        self.changed = False

    async def receipt_result(self, transaction, receipt):
        ids = receipt.manifest.get("processing_ids")
        if ids is None:
            record = await transaction.job(receipt.processing_id, locked=False)
            if record.resource_deleted:
                raise SubmissionConflict("resource_deleted")
            return record
        records = [await transaction.job(UUID(value), locked=False) for value in ids]
        if any(record is None or record.resource_deleted for record in records):
            raise SubmissionConflict("resource_deleted")
        return records

    async def mutate(
        self,
        operation,
        key,
        request,
        resource_id,
        action,
        lock=True,
        branch_id=None,
        resource_ids=None,
    ):
        owner = self.runtime.context.user_id
        async with self.repository.transaction() as transaction:
            previous = await transaction.receipt(owner, operation, key)
            if previous:
                if previous.request_hash != fingerprint(request):
                    raise SubmissionConflict("idempotency_conflict")
                if previous.accepted_at:
                    return await self.receipt_result(transaction, previous)

        @asynccontextmanager
        async def guard():
            if resource_ids is not None:
                async with self.repository.lock_resources(owner, resource_ids) as acquired:
                    yield acquired
            elif lock:
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
            async with self.repository.transaction() as transaction:
                now = transaction.now
                receipt = await transaction.reserve_mutation(
                    owner, operation, key, fingerprint(request), resource_id
                )
                if receipt.request_hash != fingerprint(request):
                    raise SubmissionConflict("idempotency_conflict")
                if receipt.accepted_at:
                    return await self.receipt_result(transaction, receipt)
                record = await action(transaction, now)
                if isinstance(record, list):
                    receipt.manifest = {"processing_ids": [str(item.id) for item in record]}
                    receipt.processing_id = record[0].id
                else:
                    receipt.processing_id = record.id
                receipt.accepted_at = now
        return record

    async def reprocess_document(self, document_id: UUID, key: UUID):
        document = await self.runtime.document_store.get(document_id)

        async def action(transaction, now):
            await self.repository.assert_inactive(self.runtime.context.user_id, document_id)
            config = self.reprocessing_config(
                document,
                await transaction.configuration_for(
                    self.runtime.context.user_id, self.workflow_config()
                ),
            )
            record = ProcessingJob(
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
            await transaction.create_jobs([record])
            transaction.event(record)
            transaction.schedule(record)
            return record

        return await self.mutate(
            "persist_document",
            key,
            {"document_id": str(document_id)},
            document_id,
            action,
        )

    async def reprocess_documents(self, document_ids: list[UUID], key: UUID):
        if not document_ids or len(document_ids) > 1000:
            raise ValueError("Select between 1 and 1000 documents")
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("Duplicate documents")
        identifiers = sorted(document_ids)

        async def action(transaction, now):
            # Validate ownership and exclusivity of the entire selection before enqueuing.
            documents = []
            for identifier in identifiers:
                documents.append(await self.runtime.document_store.get(identifier))
                await self.repository.assert_inactive(self.runtime.context.user_id, identifier)
            records = []
            baseline = await transaction.configuration_for(
                self.runtime.context.user_id, self.workflow_config()
            )
            for document in documents:
                config = self.reprocessing_config(document, baseline)
                record = ProcessingJob(
                    id=uuid4(),
                    user_id=self.runtime.context.user_id,
                    workflow="document",
                    resource_kind="document",
                    resource_id=document.id,
                    document_id=document.id,
                    workflow_version=document_workflow_version(config),
                    stage="document_persistence",
                    config=config,
                )
                records.append(record)
            await transaction.create_jobs(records)
            for record in records:
                transaction.event(record)
                transaction.schedule(record)
            return records

        return await self.mutate(
            "reprocess_documents",
            key,
            {"document_ids": [str(identifier) for identifier in identifiers]},
            identifiers[0],
            action,
            resource_ids=identifiers,
        )

    def reprocessing_config(self, document, baseline=None):
        config = deepcopy(baseline if baseline is not None else self.workflow_config())
        config["extractors"] = [
            spec
            for spec in config.get("extractors", [])
            if spec["name"] != "document_title" or not (document.title or "").strip()
        ]
        for spec in config["extractors"]:
            if "force" in spec:
                spec["force"] = True
        return config

    async def retry(self, processing_id: UUID, key: UUID, *, require_inactive=False):
        record = await self.repository.get(processing_id, self.runtime.context.user_id)
        if record is None or record.workflow in {
            "invitation_push",
            "password_recovery_email",
            "axis_preview",
            "axis_history_note",
        }:
            raise DocumentNotFoundError("Processing not found")
        lock = record.status == "failed"

        async def action(transaction, now):
            current = await transaction.job(record.id)
            if current.resource_deleted:
                raise SubmissionConflict("resource_deleted")
            if current.status != "failed":
                return current
            if not lock:
                raise SubmissionConflict("processing_state_changed")
            if require_inactive:
                # Batch maintenance must not race another queued workflow for this original.
                await self.repository.assert_inactive(current.user_id, current.resource_id)
            await self.retry_record(transaction, current, now)
            await self.resume_ancestors(transaction, current, now)
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

    async def retry_record(self, transaction, current, now):
        """Resume only retryable failed descendants; completed siblings stay untouched."""
        if current.resource_deleted:
            raise SubmissionConflict("resource_deleted")
        if current.workflow == "document" and current.workflow_version == 1:
            current.workflow_version = 2
            current.stage = "document_persistence"
            current.config = self.workflow_config()
            current.checkpoints = {}
            current.extraction_run_id = None
            current.retryable = True
        children = []
        if current.workflow == "document" and current.workflow_version in {4, 5}:
            children = await transaction.children(current.id, current.user_id)
        elif current.child_processing_id:
            child = await transaction.job(current.child_processing_id)
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
                    await self.retry_record(transaction, child, now)
                    restarted = True
            if not restarted and all(child.status == "failed" for child in children):
                raise SubmissionConflict("processing_not_retryable")
            self.wait(transaction, current, now)
            for child in children:
                if child.status in {"completed", "failed"}:
                    await transaction.wake_parent(child)
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
            self.reset(transaction, current, now)

    def wait(self, transaction, record, now):
        self.changed = True
        record.status = "waiting"
        record.stage_attempts = 0
        record.error_code = None
        record.retryable = False
        record.completed_at = None
        record.version += 1
        record.updated_at = now
        transaction.event(record)

    async def resume_ancestors(self, transaction, record, now):
        parent_id = record.parent_processing_id
        while parent_id:
            parent = await transaction.job(parent_id)
            if parent is None or parent.user_id != record.user_id or parent.resource_deleted:
                raise SubmissionConflict("resource_deleted")
            if parent.status == "failed":
                self.wait(transaction, parent, now)
            parent_id = parent.parent_processing_id

    def reset(self, transaction, current, now):
        self.changed = True
        reset_job(transaction, current, now)

    async def recover_audio(self, audio_note_id, key):
        current = await self.repository.latest(self.runtime.context.user_id, audio_note_id, "audio")
        if current is not None:
            return await self.retry(current.id, key)
        note = await self.runtime.audio_note_store.get(audio_note_id)
        if note.status != "completed" or not note.transcript:
            raise SubmissionConflict("transcription_incomplete")

        async def action(transaction, now):
            await self.repository.assert_inactive(self.runtime.context.user_id, note.id)
            record = ProcessingJob(
                id=uuid4(),
                user_id=self.runtime.context.user_id,
                workflow="audio",
                resource_kind="audio",
                resource_id=note.id,
                workflow_version=2,
                stage="document_creation",
                config=self.workflow_config(),
            )
            await transaction.create_jobs([record])
            transaction.event(record)
            transaction.schedule(record)
            self.changed = True
            return record

        return await self.mutate(
            "recover_audio", key, {"audio_note_id": str(note.id)}, note.id, action
        )
