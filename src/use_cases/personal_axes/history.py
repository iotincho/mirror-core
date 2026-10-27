"""Plan, inspect, stop and retry historical batches through semantic transactions."""

from collections import Counter
from uuid import uuid5
from zoneinfo import ZoneInfo

from src.core.documents.ports import DocumentNotFoundError, DocumentStore
from src.core.extractors.contracts import content_hash, digest
from src.core.extractors.personal_axes.history import (
    TERMINAL,
    HistoryItem,
    current_extraction,
    item_status,
)
from src.core.extractors.personal_axes.history_ports import HistoryStore
from src.core.extractors.personal_axes.models import AxisError, AxisSpecification
from src.core.extractors.personal_axes.ports import AxisDefinitions
from src.core.processing.models import ProcessingJob
from src.core.processing.retry import reset_job


class AxisHistory:
    def __init__(
        self,
        owner,
        originals: DocumentStore,
        definitions: AxisDefinitions,
        coverage,
        persistence: HistoryStore,
    ):
        self.owner, self.originals, self.definitions = owner, originals, definitions
        self.coverage_reads, self.persistence = coverage, persistence

    async def coverage(self, axis_id, document_id=None):
        return await self.coverage_reads.coverage(axis_id, document_id)

    async def notes(self, axis_id, offset=0, limit=50, q="", date_from=None, date_to=None):
        axis = await self.definitions.get(self.owner, axis_id)
        profile_hash = AxisSpecification.model_validate(
            axis.version.specification
        ).profile.fingerprint
        coverage = await self.coverage(axis_id)
        active = await self.persistence.active(self.owner, axis_id)
        result = []
        for document in await self.originals.list():
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
                    if previous["version_id"] == str(axis.current_version_id)
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
            "version_id": str(axis.current_version_id),
            "version_number": axis.version.number,
            "total": len(result),
            "remaining": sum(row["status"] not in {"current", "in_progress"} for row in result),
            "items": result[offset : offset + limit],
            "next_offset": offset + limit if offset + limit < len(result) else None,
        }

    async def start(self, axis_id, body, key):
        fingerprint = digest({"axis_id": str(axis_id), **body.model_dump(mode="json")})
        previous = await self.persistence.previous(self.owner, key)
        if previous:
            if previous.request_hash != fingerprint:
                raise AxisError("axis_history_request_conflict")
            return await self.snapshot(axis_id, previous.id)
        async with self.persistence.guard(self.owner, axis_id) as locked:
            if not locked:
                raise AxisError("axis_history_busy")
            async with self.persistence.transaction(self.owner, axis_id, planning=True) as unit:
                axis = unit.definition
                if axis.current_version_id != body.version_id:
                    raise AxisError("axis_base_version_conflict")
                spec = AxisSpecification.model_validate(axis.version.specification)
                if spec.fingerprint != axis.version.specification_hash:
                    raise AxisError("axis_specification_mismatch")
                for source in body.documents:
                    try:
                        document = await self.originals.get(source.document_id)
                    except DocumentNotFoundError:
                        raise AxisError("axis_source_unavailable") from None
                    if content_hash(document.content) != source.source_hash:
                        raise AxisError("axis_source_changed")
                batch, created = await unit.create_batch(axis_id, body.version_id, key, fingerprint)
                identifier = batch.id
                if created:
                    coverage = await self.coverage(axis_id)
                    active = await unit.active_documents(axis_id)
                    for source in body.documents:
                        old = coverage.get(str(source.document_id))
                        outcome = "in_progress" if source.document_id in active else None
                        if current_extraction(
                            old, body.version_id, source.source_hash, spec.profile.fingerprint
                        ):
                            outcome = "current"
                        item = HistoryItem(
                            batch_id=identifier,
                            document_id=source.document_id,
                            source_hash=source.source_hash,
                            outcome=outcome,
                        )
                        if outcome is None:
                            job = ProcessingJob(
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
                                        "specification": axis.version.specification,
                                    },
                                },
                                created_at=unit.now,
                            )
                            await unit.create_jobs([job])
                            item.processing_id = job.id
                            unit.schedule(job)
                        await unit.add_item(item)
            return await self.snapshot(axis_id, identifier)

    async def snapshot(self, axis_id, batch_id, offset=0, limit=50):
        view = await self.persistence.view(self.owner, axis_id, batch_id)
        batch, pairs = view.batch, view.pairs
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
                document = await self.originals.get(item.document_id)
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
            "version_number": view.version_number,
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
        await self.definitions.get(self.owner, axis_id)
        ids = await self.persistence.batch_ids(self.owner, axis_id, offset, limit + 1)
        return {
            "items": [await self.snapshot(axis_id, id) for id in ids[:limit]],
            "next_offset": offset + limit if len(ids) > limit else None,
        }

    async def stop(self, axis_id, batch_id):
        async with self.persistence.transaction(self.owner, axis_id) as unit:
            batch = await unit.batch(axis_id, batch_id)
            batch.stopped_at = batch.stopped_at or await unit.timestamp()
            pairs = await unit.stop_candidates(batch.id)
            for item, record in pairs:
                if item.outcome is not None or (
                    item.started_at is not None and record.status not in {"queued", "retrying"}
                ):
                    continue
                item.outcome = "stopped"
                record.status, record.stage = "completed", "done"
                record.completed_at = record.updated_at = unit.now
                record.generation += 1
                record.version += 1
                record.fencing_token += 1
                record.lease_owner = record.lease_expires_at = None
                record.retryable, record.error_code = False, None
        return await self.snapshot(axis_id, batch_id)

    async def retry(self, axis_id, batch_id, key):
        async with self.persistence.transaction(self.owner, axis_id) as unit:
            batch = await unit.batch(axis_id, batch_id)
            fingerprint = digest({"batch_id": str(batch_id)})
            receipt = await unit.retry_receipt(batch_id, key, fingerprint)
            if receipt.request_hash != fingerprint:
                raise AxisError("axis_history_request_conflict")
            if receipt.accepted_at is None:
                pairs = await unit.retry_candidates(batch_id)
                if pairs:
                    batch.stopped_at = None
                for item, job in pairs:
                    item.started_at = None
                    reset_job(unit, job, unit.now)
                receipt.accepted_at = unit.now
        return await self.snapshot(axis_id, batch_id)
