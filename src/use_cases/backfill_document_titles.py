"""Preview and enqueue only missing titles, reusing durable jobs across invocations."""

from collections import Counter
from uuid import uuid4, uuid5

from sqlalchemy import select

from src.core.documents.ports import DocumentNotFoundError
from src.core.documents.title_scheduling import TitleBackfillResult as TitleBackfillResult
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.processing.submissions import SubmissionConflict, SubmissionRepository
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import document_title_specification


class TitleAlreadyPresent(ValueError):
    pass


class TitleWorkPresent(ValueError):
    def __init__(self, result):
        self.result = result


class BackfillDocumentTitles:
    operation = "backfill_document_title"

    def __init__(self, repository, runtime):
        self.repository, self.runtime = repository, runtime
        self.owner = runtime.context.user_id
        self.submissions = SubmissionRepository(repository)
        self.requests = RequestProcessing(repository, runtime)

    def key(self, document_id):
        # Changing the current model/profile must not silently create another paid run.
        return uuid5(self.owner, f"backfill-document-title/v1:{document_id}")

    async def deleted(self, document_id, session):
        return (
            await session.scalar(
                select(ProcessingRecord.id)
                .where(
                    ProcessingRecord.user_id == self.owner,
                    ProcessingRecord.resource_id == document_id,
                    ProcessingRecord.resource_deleted.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def has_title_specification(config):
        return any(
            isinstance(spec, dict) and spec.get("name") == "document_title"
            for spec in config.get("extractors") or []
        )

    async def unavailable(self, document_ids, session=None):
        """Batch-filter existing work, including uploads reserved before their job exists."""
        if session is None:
            async with self.repository.sessions() as session:
                return await self.unavailable(document_ids, session)
        records = await session.scalars(
            select(ProcessingRecord)
            .where(
                ProcessingRecord.user_id == self.owner,
                ProcessingRecord.resource_id.in_(document_ids),
            )
            .order_by(ProcessingRecord.created_at.desc())
        )
        blocked = {}
        for record in records:
            previous = blocked.get(record.resource_id)
            if record.resource_deleted:
                state = "deleted"
            elif previous and previous.status == "deleted":
                continue
            elif record.status in {"queued", "running", "waiting", "retrying"}:
                state = "busy"
            elif previous and previous.status == "busy":
                continue
            elif record.extractor_name == "document_title" or self.has_title_specification(
                record.config
            ):
                state = "failed" if record.status == "failed" else "completed"
            else:
                continue
            blocked[record.resource_id] = TitleBackfillResult(record.resource_id, state, record.id)
        receipts = await session.scalars(
            select(ProcessingReceipt).where(
                ProcessingReceipt.user_id == self.owner,
                ProcessingReceipt.resource_id.in_(document_ids),
                ProcessingReceipt.operation != self.operation,
            )
        )
        for receipt in receipts:
            if receipt.accepted_at is None or self.has_title_specification(receipt.config):
                blocked.setdefault(
                    receipt.resource_id,
                    TitleBackfillResult(
                        receipt.resource_id,
                        "already_scheduled",
                        receipt.processing_id,
                    ),
                )
        return blocked

    async def inspect(self, document_id):
        receipt = await self.submissions.get(self.owner, self.operation, self.key(document_id))
        if receipt is not None and receipt.accepted_at is not None:
            record = await self.repository.get(receipt.processing_id, self.owner)
            if record is None or record.resource_deleted:
                return TitleBackfillResult(document_id, "deleted")
            if record.status == "failed":
                status = "retryable" if record.retryable else "failed"
                if record.retryable:
                    try:
                        await self.repository.assert_inactive(self.owner, document_id)
                    except ValueError:
                        status = "busy"
            else:
                status = "completed" if record.status == "completed" else "already_scheduled"
            # A title may already be in the original while its graph projection still needs retry.
            return TitleBackfillResult(document_id, status, record.id)
        try:
            document = await self.runtime.document_store.get(document_id)
        except DocumentNotFoundError:
            return TitleBackfillResult(document_id, "missing")
        async with self.repository.sessions() as session:
            if await self.deleted(document_id, session):
                return TitleBackfillResult(document_id, "deleted")
        if document.title and document.title.strip():
            return TitleBackfillResult(document_id, "titled")
        blocked = await self.unavailable([document_id])
        if document_id in blocked:
            return blocked[document_id]
        try:
            await self.repository.assert_inactive(self.owner, document_id)
        except ValueError:
            return TitleBackfillResult(document_id, "busy")
        return TitleBackfillResult(document_id, "eligible")

    async def execute(self, document_id, *, apply=False, retry_failed=True):
        result = await self.inspect(document_id)
        if not apply or result.status not in {"eligible", "retryable"}:
            return result
        if result.status == "retryable" and not retry_failed:
            return result
        try:
            if result.status == "retryable":
                record = await self.repository.get(result.processing_id, self.owner)
                retry_key = uuid5(self.owner, f"backfill-title-retry:{record.id}:{record.version}")
                record = await self.requests.retry(record.id, retry_key, require_inactive=True)
                return TitleBackfillResult(document_id, "retried", record.id)

            created = False

            async def action(session, now):
                nonlocal created
                # Recheck under the exclusive resource guard before committing receipt/job/outbox.
                if await self.deleted(document_id, session):
                    raise SubmissionConflict("resource_deleted")
                document = await self.runtime.document_store.get(document_id)
                if document.title and document.title.strip():
                    raise TitleAlreadyPresent()
                blocked = await self.unavailable([document_id], session)
                if document_id in blocked:
                    raise TitleWorkPresent(blocked[document_id])
                await self.repository.assert_inactive(self.owner, document_id)
                record = ProcessingRecord(
                    id=uuid4(),
                    user_id=self.owner,
                    workflow="document",
                    workflow_version=4,
                    resource_kind="document",
                    resource_id=document_id,
                    document_id=document_id,
                    stage="document_persistence",
                    config={
                        "document_workflow_version": 4,
                        "extractors": [document_title_specification()],
                    },
                )
                session.add(record)
                await session.flush()
                self.repository.event(session, record)
                self.repository.schedule(session, record)
                created = True
                return record

            record = await self.requests.mutate(
                self.operation,
                self.key(document_id),
                {"document_id": str(document_id)},
                document_id,
                action,
            )
            return TitleBackfillResult(
                document_id, "queued" if created else "already_scheduled", record.id
            )
        except TitleAlreadyPresent:
            return TitleBackfillResult(document_id, "titled")
        except TitleWorkPresent as error:
            return error.result
        except DocumentNotFoundError:
            return TitleBackfillResult(document_id, "missing")
        except ValueError as error:
            if str(error) == "processing_active":
                return TitleBackfillResult(document_id, "busy")
            if str(error) == "resource_deleted":
                return TitleBackfillResult(document_id, "deleted")
            raise

    async def run(self, *, apply=False, limit=100, document_ids=None):
        if limit < 1:
            raise ValueError("limit_must_be_positive")
        ids = (
            sorted(set(document_ids), key=str)
            if document_ids is not None
            else sorted(
                (document.id for document in await self.runtime.document_store.list()), key=str
            )
        )
        results, selected = [], 0
        for document_id in ids:
            preview = await self.inspect(document_id)
            if preview.status in {"eligible", "retryable"}:
                if selected >= limit:
                    result = TitleBackfillResult(document_id, "deferred", preview.processing_id)
                else:
                    result = await self.execute(document_id, apply=apply) if apply else preview
                    if result.status in {"eligible", "retryable", "queued", "retried"}:
                        selected += 1
            else:
                result = preview
            results.append(result)
        return {
            "workspace": str(self.owner),
            "mode": "apply" if apply else "preview",
            "limit": limit,
            "total_documents": len(ids),
            "counts": dict(Counter(result.status for result in results)),
            "documents": [result.serializable() for result in results],
        }
