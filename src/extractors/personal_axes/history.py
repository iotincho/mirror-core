"""Plan and recover historical work using the existing transactional outbox."""

from collections import Counter
from uuid import uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.models import ProcessingReceipt, ProcessingRecord
from src.bootstrap.processing import AxisHistoryRequests as RequestProcessing
from src.core.documents.ports import DocumentNotFoundError
from src.core.extractors.contracts import content_hash, digest
from src.extractors.personal_axes.access import laboratory_available
from src.extractors.personal_axes.contracts import AxisError, AxisSpecification
from src.extractors.personal_axes.exploration import AxisExploration
from src.extractors.personal_axes.history_models import AxisHistoryBatch, AxisHistoryItem
from src.extractors.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.extractors.personal_axes.store import rows

ACTIVE = ("queued", "running", "retrying", "waiting")
TERMINAL = {"completed", "skipped", "stopped", "changed", "deleted", "superseded", "failed"}


def current_extraction(previous, version_id, source_hash, profile_hash):
    return bool(
        previous
        and previous["version_id"] == str(version_id)
        and previous["content_hash"] == source_hash
        and previous.get("profile_hash") == profile_hash
    )


def item_status(item, record):
    if item.outcome in {"current", "in_progress"}:
        return "skipped"
    if item.outcome:
        return item.outcome
    if record.resource_deleted:
        return "deleted"
    return record.status


class AxisHistory:
    def __init__(self, previews):
        self.previews = previews
        self.owner, self.runtime, self.repo = previews.owner, previews.runtime, previews.processing
        self.axes = previews.axes

    async def coverage(self, axis_id, document_id=None):
        async with AxisExploration(self.previews).read(axis_id, None) as tx:
            if tx is None:
                return {}
            params = {"axis_id": str(axis_id)}
            condition = "axis_id=:axis_id"
            if document_id:
                condition += " AND document_id=:document_id"
                params["document_id"] = str(document_id)
            runs = rows(
                await tx.query(
                    "SELECT document_id, version_id, content_hash, profile_hash "
                    "FROM AxisExtraction "
                    f"WHERE {condition} LIMIT 100001",
                    params,
                )
            )
            counts = rows(
                await tx.query(
                    "SELECT document_id, count(*) AS total FROM AxisFinding "
                    f"WHERE {condition} GROUP BY document_id LIMIT 100001",
                    params,
                )
            )
            if len(runs) > 100000 or len(counts) > 100000:
                raise AxisError("axis_catalogue_limit", 422)
        findings = {row["document_id"]: row["total"] for row in counts}
        return {
            row["document_id"]: {**row, "findings_count": findings.get(row["document_id"], 0)}
            for row in runs
        }

    async def active_documents(self, session, axis_id):
        historical = set(
            (
                await session.scalars(
                    select(AxisHistoryItem.document_id)
                    .join(AxisHistoryBatch, AxisHistoryItem.batch_id == AxisHistoryBatch.id)
                    .join(ProcessingRecord, AxisHistoryItem.processing_id == ProcessingRecord.id)
                    .where(
                        AxisHistoryBatch.user_id == self.owner,
                        AxisHistoryBatch.axis_id == axis_id,
                        AxisHistoryItem.outcome.is_(None),
                        ProcessingRecord.status.in_(ACTIVE),
                    )
                )
            ).all()
        )
        regular = set(
            (
                await session.scalars(
                    select(ProcessingRecord.resource_id).where(
                        ProcessingRecord.user_id == self.owner,
                        ProcessingRecord.resource_kind == "document",
                        ProcessingRecord.status.in_(ACTIVE),
                        or_(
                            (ProcessingRecord.workflow == "extractor")
                            & (ProcessingRecord.extractor_key == f"axis:{axis_id}"),
                            (ProcessingRecord.workflow == "document")
                            & ProcessingRecord.config["extractors"].contains(
                                [{"axis_id": str(axis_id)}]
                            ),
                        ),
                    )
                )
            ).all()
        )
        return historical | regular

    async def notes(self, axis_id, offset=0, limit=50, q="", date_from=None, date_to=None):
        axis = await self.axes.get(self.owner, axis_id)
        profile_hash = AxisSpecification.model_validate(
            axis["version"]["specification"]
        ).profile.fingerprint
        coverage = await self.coverage(axis_id)
        async with self.repo.sessions() as session:
            active = await self.active_documents(session, axis_id)
        result = []
        for document in await self.runtime.document_store.list():
            date = document.authored_at or document.created_at
            title = document.title or "Nota sin título"
            if (
                (q and q.casefold() not in title.casefold())
                or (
                    date_from
                    and date.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).date()
                    < date_from
                )
                or (
                    date_to
                    and date.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).date() > date_to
                )
            ):
                continue
            source = content_hash(document.content)
            previous = coverage.get(str(document.id))
            status = "unanalysed"
            if previous:
                status = (
                    "current"
                    if previous["version_id"] == axis["current_version_id"]
                    else "previous_version"
                )
                if status == "current" and previous.get("profile_hash") != profile_hash:
                    status = "unanalysed"
                if previous["content_hash"] != source:
                    status = "changed"
            if document.id in active and status != "current":
                status = "in_progress"
            result.append(
                {
                    "document_id": document.id,
                    "title": title,
                    "date": date,
                    "source_hash": source,
                    "status": status,
                    "findings_count": previous["findings_count"] if previous else 0,
                }
            )
        result.sort(key=lambda row: (row["date"], str(row["document_id"])), reverse=True)
        return {
            "version_id": axis["current_version_id"],
            "version_number": axis["version"]["number"],
            "total": len(result),
            "remaining": sum(row["status"] not in {"current", "in_progress"} for row in result),
            "items": result[offset : offset + limit],
            "next_offset": offset + limit if offset + limit < len(result) else None,
        }

    async def _batch(self, session, axis_id, batch_id, *, lock=False):
        query = select(AxisHistoryBatch).where(
            AxisHistoryBatch.id == batch_id,
            AxisHistoryBatch.user_id == self.owner,
            AxisHistoryBatch.axis_id == axis_id,
        )
        batch = await session.scalar(query.with_for_update() if lock else query)
        if batch is None:
            raise AxisError("axis_history_not_found", 404)
        return batch

    async def start(self, axis_id, body, key):
        fingerprint = digest({"axis_id": str(axis_id), **body.model_dump(mode="json")})
        async with self.repo.sessions() as session:
            previous = await session.scalar(
                select(AxisHistoryBatch).where(
                    AxisHistoryBatch.user_id == self.owner, AxisHistoryBatch.request_key == key
                )
            )
            if previous:
                if previous.request_hash != fingerprint:
                    raise AxisError("axis_history_request_conflict")
                return await self.snapshot(axis_id, previous.id)
        async with self.repo.lock_resource(self.owner, axis_id) as locked:
            if not locked:
                raise AxisError("axis_history_busy")
            async with self.repo.sessions.begin() as session:
                axis = await session.scalar(
                    select(PersonalAxis)
                    .where(PersonalAxis.id == axis_id, PersonalAxis.user_id == self.owner)
                    .with_for_update()
                )
                if axis is None or not await laboratory_available(session, self.owner):
                    raise AxisError("axis_not_found", 404)
                if axis.current_version_id != body.version_id:
                    raise AxisError("axis_base_version_conflict")
                version = await session.get(PersonalAxisVersion, body.version_id)
                spec = AxisSpecification.model_validate(version.specification)
                if spec.fingerprint != version.specification_hash:
                    raise AxisError("axis_specification_mismatch", 503)
                # Ownership and all hashes are validated before creating executable jobs.
                for source in body.documents:
                    try:
                        document = await self.runtime.document_store.get(source.document_id)
                    except DocumentNotFoundError:
                        raise AxisError("axis_source_unavailable", 409) from None
                    if content_hash(document.content) != source.source_hash:
                        raise AxisError("axis_source_changed")
                now = await session.scalar(select(func.clock_timestamp()))
                identifier = uuid4()
                await session.execute(
                    insert(AxisHistoryBatch)
                    .values(
                        id=identifier,
                        user_id=self.owner,
                        axis_id=axis_id,
                        version_id=body.version_id,
                        request_key=key,
                        request_hash=fingerprint,
                        created_at=now,
                    )
                    .on_conflict_do_nothing()
                )
                batch = await session.scalar(
                    select(AxisHistoryBatch)
                    .where(
                        AxisHistoryBatch.user_id == self.owner, AxisHistoryBatch.request_key == key
                    )
                    .with_for_update()
                )
                if batch.request_hash != fingerprint:
                    raise AxisError("axis_history_request_conflict")
                if batch.id != identifier:
                    identifier = batch.id
                else:
                    coverage, active = (
                        await self.coverage(axis_id),
                        await self.active_documents(session, axis_id),
                    )
                    for source in body.documents:
                        old = coverage.get(str(source.document_id))
                        outcome = "in_progress" if source.document_id in active else None
                        if current_extraction(
                            old, body.version_id, source.source_hash, spec.profile.fingerprint
                        ):
                            outcome = "current"
                        item = AxisHistoryItem(
                            batch_id=identifier,
                            document_id=source.document_id,
                            source_hash=source.source_hash,
                            outcome=outcome,
                        )
                        if outcome is None:
                            job = ProcessingRecord(
                                id=uuid5(identifier, str(source.document_id)),
                                user_id=self.owner,
                                workflow="axis_history_note",
                                workflow_version=1,
                                resource_kind="document",
                                resource_id=source.document_id,
                                document_id=source.document_id,
                                stage="extraction",
                                extraction_run_id=uuid5(
                                    identifier, "run:" + str(source.document_id)
                                ),
                                extractor_name="personal_axis",
                                extractor_key=f"axis:{axis_id}",
                                config={
                                    "batch_id": str(identifier),
                                    "source_hash": source.source_hash,
                                    "extractor": {
                                        "name": "personal_axis",
                                        "axis_id": str(axis_id),
                                        "version_id": str(body.version_id),
                                        "specification": version.specification,
                                    },
                                },
                                created_at=now,
                            )
                            session.add(job)
                            await session.flush()
                            item.processing_id = job.id
                            self.repo.schedule(session, job)
                        session.add(item)
            return await self.snapshot(axis_id, identifier)

    async def snapshot(self, axis_id, batch_id, offset=0, limit=50):
        async with self.repo.sessions() as session:
            batch = await self._batch(session, axis_id, batch_id)
            version = await session.get(PersonalAxisVersion, batch.version_id)
            pairs = (
                await session.execute(
                    select(AxisHistoryItem, ProcessingRecord)
                    .outerjoin(
                        ProcessingRecord, AxisHistoryItem.processing_id == ProcessingRecord.id
                    )
                    .where(AxisHistoryItem.batch_id == batch.id)
                    .order_by(AxisHistoryItem.document_id)
                )
            ).all()
        counts = Counter(item_status(item, record) for item, record in pairs)
        finished = sum(value for name, value in counts.items() if name in TERMINAL)
        status = (
            "running"
            if finished < len(pairs)
            else (
                "stopped"
                if batch.stopped_at
                else "completed_with_errors"
                if any(counts[name] for name in ("failed", "changed", "deleted"))
                else "completed"
            )
        )
        items = []
        for item, record in pairs[offset : offset + limit]:
            try:
                document = await self.runtime.document_store.get(item.document_id)
                title = document.title or "Nota sin título"
            except DocumentNotFoundError:
                title = "Nota no disponible"
            items.append(
                {
                    "document_id": item.document_id,
                    "title": title,
                    "status": item_status(item, record),
                    "retryable": bool(
                        record
                        and record.status == "failed"
                        and record.retryable
                        and not record.resource_deleted
                        and item.outcome is None
                    ),
                }
            )
        return {
            "id": batch.id,
            "axis_id": batch.axis_id,
            "version_id": batch.version_id,
            "version_number": version.number,
            "created_at": batch.created_at,
            "stopped_at": batch.stopped_at,
            "status": status,
            "total": len(pairs),
            "finished": finished,
            "counts": dict(counts),
            "retryable": sum(
                bool(
                    record
                    and record.status == "failed"
                    and record.retryable
                    and not record.resource_deleted
                    and item.outcome is None
                )
                for item, record in pairs
            ),
            "items": items,
            "next_offset": offset + limit if offset + limit < len(pairs) else None,
        }

    async def batches(self, axis_id, offset=0, limit=10):
        await self.axes.get(self.owner, axis_id)
        async with self.repo.sessions() as session:
            ids = list(
                (
                    await session.scalars(
                        select(AxisHistoryBatch.id)
                        .where(
                            AxisHistoryBatch.axis_id == axis_id,
                            AxisHistoryBatch.user_id == self.owner,
                        )
                        .order_by(AxisHistoryBatch.created_at.desc(), AxisHistoryBatch.id.desc())
                        .offset(offset)
                        .limit(limit + 1)
                    )
                ).all()
            )
        return {
            "items": [await self.snapshot(axis_id, id) for id in ids[:limit]],
            "next_offset": offset + limit if len(ids) > limit else None,
        }

    async def stop(self, axis_id, batch_id):
        async with self.repo.sessions.begin() as session:
            batch = await self._batch(session, axis_id, batch_id, lock=True)
            batch.stopped_at = batch.stopped_at or await session.scalar(
                select(func.clock_timestamp())
            )
            records = (
                await session.scalars(
                    select(ProcessingRecord)
                    .join(AxisHistoryItem, AxisHistoryItem.processing_id == ProcessingRecord.id)
                    .where(
                        AxisHistoryItem.batch_id == batch.id,
                        AxisHistoryItem.outcome.is_(None),
                        ProcessingRecord.status.in_(ACTIVE),
                    )
                    .where(
                        or_(
                            AxisHistoryItem.started_at.is_(None),
                            ProcessingRecord.status.in_(["queued", "retrying"]),
                        )
                    )
                    .with_for_update(of=ProcessingRecord)
                )
            ).all()
            now = await session.scalar(select(func.clock_timestamp()))
            for record in records:
                item = await session.get(
                    AxisHistoryItem, (batch.id, record.resource_id), with_for_update=True
                )
                if item.outcome is not None or (
                    item.started_at is not None and record.status not in {"queued", "retrying"}
                ):
                    continue
                item.outcome = "stopped"
                record.status, record.stage = "completed", "done"
                record.completed_at = record.updated_at = now
                record.generation += 1
                record.version += 1
                record.fencing_token += 1
                record.lease_owner = record.lease_expires_at = None
                record.retryable, record.error_code = False, None
        return await self.snapshot(axis_id, batch_id)

    async def retry(self, axis_id, batch_id, key):
        async with self.repo.sessions.begin() as session:
            batch = await self._batch(session, axis_id, batch_id, lock=True)
            fingerprint = digest({"batch_id": str(batch_id)})
            await session.execute(
                insert(ProcessingReceipt)
                .values(
                    id=uuid4(),
                    user_id=self.owner,
                    operation="axis_history_retry",
                    key=key,
                    request_hash=fingerprint,
                    resource_kind="axis_history",
                    resource_id=batch_id,
                    config={},
                    manifest={},
                    lease_token=uuid4(),
                    lease_expires_at=func.now(),
                )
                .on_conflict_do_nothing()
            )
            receipt = await session.scalar(
                select(ProcessingReceipt)
                .where(
                    ProcessingReceipt.user_id == self.owner,
                    ProcessingReceipt.operation == "axis_history_retry",
                    ProcessingReceipt.key == key,
                )
                .with_for_update()
            )
            if receipt.request_hash != fingerprint:
                raise AxisError("axis_history_request_conflict")
            if receipt.accepted_at is None:
                jobs = (
                    await session.scalars(
                        select(ProcessingRecord)
                        .join(AxisHistoryItem, AxisHistoryItem.processing_id == ProcessingRecord.id)
                        .where(
                            AxisHistoryItem.batch_id == batch_id,
                            AxisHistoryItem.outcome.is_(None),
                            ProcessingRecord.status == "failed",
                            ProcessingRecord.retryable.is_(True),
                            ProcessingRecord.resource_deleted.is_(False),
                        )
                        .with_for_update(of=ProcessingRecord)
                    )
                ).all()
                now = await session.scalar(select(func.clock_timestamp()))
                use_case = RequestProcessing(self.repo, self.runtime)
                if jobs:
                    batch.stopped_at = None
                for job in jobs:
                    item = await session.get(
                        AxisHistoryItem, (batch.id, job.resource_id), with_for_update=True
                    )
                    item.started_at = None
                    use_case.reset(session, job, now)
                receipt.accepted_at = now
        return await self.snapshot(axis_id, batch_id)
