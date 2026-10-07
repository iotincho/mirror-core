"""Reserve durable request identity before writing an original to the filesystem."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.processing.configuration import document_workflow_version
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.processing.repository import ProcessingRepository


class SubmissionConflict(ValueError):
    pass


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class SubmissionRepository:
    def __init__(self, processing: ProcessingRepository):
        self.processing = processing
        self.sessions = processing.sessions

    async def reserve(
        self,
        *,
        user_id: UUID,
        operation: str,
        key: UUID,
        request_hash: str,
        resource_kind: str,
        resource_id: UUID | None,
        config: dict,
        manifest: dict,
    ) -> ProcessingReceipt:
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            receipt_id = uuid4()
            inserted = await session.scalar(
                insert(ProcessingReceipt)
                .values(
                    id=receipt_id,
                    user_id=user_id,
                    operation=operation,
                    key=key,
                    request_hash=request_hash,
                    resource_kind=resource_kind,
                    resource_id=resource_id or uuid4(),
                    config=config,
                    manifest=manifest,
                    lease_token=uuid4(),
                    lease_expires_at=now + timedelta(seconds=90),
                    created_at=now,
                )
                .on_conflict_do_nothing()
                .returning(ProcessingReceipt.id)
            )
            query = (
                select(ProcessingReceipt)
                .where(
                    ProcessingReceipt.user_id == user_id,
                    ProcessingReceipt.operation == operation,
                    ProcessingReceipt.key == key,
                )
                .with_for_update()
            )
            receipt = await session.scalar(query)
            if receipt is None and resource_id and operation.startswith("upload_"):
                receipt = await session.scalar(
                    select(ProcessingReceipt)
                    .where(
                        ProcessingReceipt.user_id == user_id,
                        ProcessingReceipt.operation == operation,
                        ProcessingReceipt.resource_id == resource_id,
                        ProcessingReceipt.is_original.is_(True),
                    )
                    .with_for_update()
                )
            if receipt is None:
                raise SubmissionConflict("resource_already_exists")
            if receipt.request_hash != request_hash or (
                resource_id is not None and receipt.resource_id != resource_id
            ):
                raise SubmissionConflict("idempotency_conflict")
            if receipt.key != key:
                if receipt.accepted_at is None:
                    raise SubmissionConflict("upload_in_progress")
                # Bind this successful alias request too; its key cannot later create another note.
                alias_id = uuid4()
                alias = await session.scalar(
                    insert(ProcessingReceipt)
                    .values(
                        id=alias_id,
                        user_id=user_id,
                        operation=operation,
                        key=key,
                        request_hash=request_hash,
                        is_original=False,
                        resource_kind=resource_kind,
                        resource_id=receipt.resource_id,
                        config=receipt.config,
                        manifest=receipt.manifest,
                        processing_id=receipt.processing_id,
                        lease_token=uuid4(),
                        lease_expires_at=now,
                        created_at=receipt.created_at,
                        accepted_at=now,
                    )
                    .on_conflict_do_nothing()
                    .returning(ProcessingReceipt.id)
                )
                if alias is None:
                    receipt = await session.scalar(query)
                    if receipt.request_hash != request_hash or receipt.resource_id != resource_id:
                        raise SubmissionConflict("idempotency_conflict")
                else:
                    receipt = await session.get(ProcessingReceipt, alias_id)
            if receipt.accepted_at is None and inserted is None:
                if receipt.lease_expires_at > now:
                    raise SubmissionConflict("upload_in_progress")
                receipt.lease_token = uuid4()
                receipt.lease_expires_at = now + timedelta(seconds=90)
        return receipt

    async def accept(self, receipt: ProcessingReceipt) -> ProcessingRecord:
        async with self.sessions.begin() as session:
            current = await session.get(ProcessingReceipt, receipt.id, with_for_update=True)
            if current.accepted_at is not None:
                return await session.get(ProcessingRecord, current.processing_id)
            if current.lease_token != receipt.lease_token:
                raise SubmissionConflict("upload_in_progress")
            if not await self.processing.workspace_active(receipt.user_id):
                raise SubmissionConflict("workspace_unavailable")
            record = ProcessingRecord(
                id=uuid4(),
                user_id=receipt.user_id,
                workflow="document" if receipt.resource_kind == "document" else "audio",
                workflow_version=document_workflow_version(receipt.config)
                if receipt.resource_kind == "document"
                else 2,
                stage="document_persistence"
                if receipt.resource_kind == "document"
                else "transcription",
                resource_kind=receipt.resource_kind,
                resource_id=receipt.resource_id,
                document_id=receipt.resource_id if receipt.resource_kind == "document" else None,
                config=receipt.config,
            )
            session.add(record)
            await session.flush()
            self.processing.event(session, record)
            self.processing.schedule(session, record)
            current.processing_id = record.id
            current.accepted_at = await session.scalar(select(func.clock_timestamp()))
        return record

    async def release(self, receipt: ProcessingReceipt):
        """Allow immediate retry after a failed write, without deleting the receipt."""
        async with self.sessions.begin() as session:
            current = await session.get(ProcessingReceipt, receipt.id, with_for_update=True)
            if current.lease_token == receipt.lease_token and current.accepted_at is None:
                current.lease_expires_at = await session.scalar(select(func.clock_timestamp()))

    async def claim_pending(self):
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            rows = list(
                (
                    await session.scalars(
                        select(ProcessingReceipt)
                        .where(
                            ProcessingReceipt.accepted_at.is_(None),
                            ProcessingReceipt.operation.in_(["upload_document", "upload_audio"]),
                            ProcessingReceipt.lease_expires_at <= now,
                        )
                        .limit(20)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for receipt in rows:
                receipt.lease_token = uuid4()
                receipt.lease_expires_at = now + timedelta(seconds=90)
        return rows
