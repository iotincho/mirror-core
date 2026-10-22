"""Own the temporary evaluation and permanent approval boundaries of personal axes."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select

from src.extractors.personal_axes.contracts import (
    AxisError,
    AxisSpecification,
    PreviewRequest,
)
from src.extractors.personal_axes.extractor import PersonalAxisExtractor
from src.extractors.personal_axes.preview_projection import project_preview
from src.extractors.personal_axes.preview_store import PreviewStore
from src.extractors.personal_axes.repository import AxisRepository
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.services.document_store import DocumentNotFoundError


class AxisPreviews:
    def __init__(self, processing, runtime, settings):
        self.processing, self.runtime, self.settings = processing, runtime, settings
        self.owner = runtime.context.user_id
        self.axes = AxisRepository(processing.sessions)

    def store(self, preview_id):
        return PreviewStore(self.runtime.context.filesystem_root, preview_id)

    @asynccontextmanager
    async def guard(self, preview_id):
        async with self.processing.lock_resource(self.owner, preview_id) as locked:
            if not locked:
                raise AxisError("axis_preview_busy")
            yield

    @asynccontextmanager
    async def source_guard(self, value, preview_id):
        # One connection for the whole sample, not one per note (pool exhaustion).
        async with self.processing.lock_resources(
            self.owner, [UUID(identifier) for identifier in value["sources"]], shared=True
        ) as locked:
            if not locked:
                raise AxisError("axis_source_busy")
            yield await self.documents(value)

    async def documents(self, value):
        documents = []
        for identifier, expected in value["sources"].items():
            try:
                document = await self.runtime.document_store.get(UUID(identifier))
            except DocumentNotFoundError:
                raise AxisError("axis_source_unavailable") from None
            from src.extractors.contracts import content_hash

            if content_hash(document.content) != expected:
                raise AxisError("axis_source_changed")
            documents.append(document)
        return documents

    async def live(self, preview_id):
        record = await self.processing.get(preview_id, self.owner)
        if record is None or record.workflow != "axis_preview":
            raise AxisError("axis_preview_not_found", 404)
        if record.resource_deleted:
            raise AxisError("axis_source_unavailable")
        if record.expires_at <= datetime.now(UTC):
            raise AxisError("axis_preview_expired", 410)
        return record, await self.store(preview_id).input()

    async def receipt(self, operation, key):
        async with self.processing.sessions() as session:
            return await session.scalar(
                select(ProcessingReceipt).where(
                    ProcessingReceipt.user_id == self.owner,
                    ProcessingReceipt.operation == operation,
                    ProcessingReceipt.key == key,
                )
            )

    async def request(self, request: PreviewRequest, key: UUID):
        preview_id = uuid5(self.owner, f"axis-preview:{key}")
        store = self.store(preview_id)
        # Replays must also work while the worker holds the preview execution lock.
        receipt = await self.receipt("axis_preview", key)
        if receipt is not None:
            if receipt.request_hash != request.fingerprint:
                raise AxisError("idempotency_conflict")
            return await self.snapshot(preview_id)
        if await self.axes.approved(self.owner, preview_id, request.fingerprint) is not None:
            raise AxisError("axis_preview_already_accepted", 410)
        async with self.guard(preview_id):
            async with self.processing.sessions() as session:
                receipt = await session.scalar(
                    select(ProcessingReceipt).where(
                        ProcessingReceipt.user_id == self.owner,
                        ProcessingReceipt.operation == "axis_preview",
                        ProcessingReceipt.key == key,
                    )
                )
            if receipt is not None:
                if receipt.request_hash != request.fingerprint:
                    raise AxisError("idempotency_conflict")
                return await self.snapshot(preview_id)
            if request.axis_id:
                axis = await self.axes.get(self.owner, request.axis_id)
                if axis["current_version_id"] != str(request.base_version_id):
                    raise AxisError("axis_base_version_conflict")
            previous = None
            if request.previous_preview_id:
                _, prior = await self.live(request.previous_preview_id)
                previous_request = PreviewRequest.model_validate(prior["request"])
                if (
                    previous_request.draft_id != request.draft_id
                    or previous_request.axis_id != request.axis_id
                    or previous_request.base_version_id != request.base_version_id
                ):
                    raise AxisError("axis_draft_conflict")
                if request.revision <= previous_request.revision:
                    raise AxisError("axis_revision_conflict")
                history = previous_request.adjustments
                if request.adjustments[: len(history)] != history:
                    raise AxisError("axis_adjustment_history_required")
                if (
                    request.document_ids != previous_request.document_ids
                    and not request.change_sample
                ):
                    raise AxisError("axis_sample_change_required")
                if not request.change_sample:
                    await self.documents(prior)
                if request.mode == "repeat" and (
                    request.purpose != previous_request.purpose
                    or request.title != previous_request.title
                    or request.adjustments != previous_request.adjustments
                ):
                    raise AxisError("axis_repeat_definition_changed")
                saved = await self.store(request.previous_preview_id).read("specification")
                if saved is None:
                    raise AxisError("axis_previous_prompt_not_ready")
                previous = saved["specification"]
            configuration = {
                "provider": self.settings.llm_provider,
                "model": self.settings.openai_model,
                "max_output_tokens": self.settings.personal_axes_max_output_tokens,
                "max_input_chars": self.settings.personal_axes_max_input_chars,
            }
            if request.mode == "repeat":
                configuration = {key: previous[key] for key in configuration}
            if not configuration["model"] or configuration["provider"] != "openai":
                raise AxisError("axis_provider_configuration", 503)
            old = await store.read("input")
            if old is not None and old["revision_hash"] != request.fingerprint:
                raise AxisError("idempotency_conflict")
            async with self.processing.lock_resources(self.owner, request.document_ids) as locked:
                if not locked:
                    raise AxisError("axis_source_busy")
                from src.extractors.contracts import content_hash

                sources = {}
                for identifier in request.document_ids:
                    try:
                        document = await self.runtime.document_store.get(identifier)
                    except DocumentNotFoundError:
                        raise AxisError("axis_source_unavailable", 404) from None
                    if len(document.content) > configuration["max_input_chars"]:
                        raise AxisError("axis_input_too_long", 422)
                    sources[str(identifier)] = content_hash(document.content)
                if request.previous_preview_id and not request.change_sample:
                    if sources != prior["sources"]:
                        raise AxisError("axis_source_changed")
                async with self.processing.sessions.begin() as session:
                    now = await session.scalar(select(func.clock_timestamp()))
                    quota_lock = await session.scalar(
                        select(
                            func.pg_try_advisory_xact_lock(
                                func.hashtextextended(f"{self.owner}:axis-preview-quota", 0)
                            )
                        )
                    )
                    if not quota_lock:
                        raise AxisError("axis_preview_limit", 429)
                    pending = await session.scalar(
                        select(func.count())
                        .select_from(ProcessingRecord)
                        .where(
                            ProcessingRecord.user_id == self.owner,
                            ProcessingRecord.workflow == "axis_preview",
                            ProcessingRecord.expires_at > now,
                            ProcessingRecord.status.in_(["queued", "running", "retrying"]),
                        )
                    )
                    if pending >= self.settings.personal_axes_max_pending_previews:
                        raise AxisError("axis_preview_limit", 429)
                    value = old or {
                        "request": request.model_dump(mode="json"),
                        "revision_hash": request.fingerprint,
                        "sources": sources,
                        "configuration": configuration,
                        "previous_specification": previous,
                        "expires_at": (
                            now + timedelta(hours=self.settings.personal_axes_preview_hours)
                        ).isoformat(),
                    }
                    if datetime.fromisoformat(value["expires_at"]) <= now:
                        raise AxisError("axis_preview_expired", 410)
                    if value["sources"] != sources:
                        raise AxisError("axis_source_changed")
                    # Files precede executable SQL/outbox. An interrupted transaction leaves
                    # an immutable, deterministic orphan; a replay can reuse it safely.
                    await store.write("input", value)
                    record = ProcessingRecord(
                        id=preview_id,
                        user_id=self.owner,
                        workflow="axis_preview",
                        workflow_version=1,
                        resource_kind="axis_preview",
                        resource_id=preview_id,
                        stage="prompt_generation",
                        config={"preview_id": str(preview_id), "document_ids": list(sources)},
                        expires_at=datetime.fromisoformat(value["expires_at"]),
                    )
                    session.add(record)
                    await session.flush()
                    session.add(
                        ProcessingReceipt(
                            user_id=self.owner,
                            operation="axis_preview",
                            key=key,
                            request_hash=request.fingerprint,
                            resource_kind="axis_preview",
                            resource_id=preview_id,
                            config={},
                            manifest={},
                            processing_id=preview_id,
                            lease_token=uuid5(preview_id, "receipt"),
                            lease_expires_at=now,
                            accepted_at=now,
                            expires_at=record.expires_at,
                        )
                    )
                    self.processing.schedule(session, record)
            return await self.snapshot(preview_id)

    async def snapshot(self, preview_id):
        record, value = await self.live(preview_id)
        documents = {str(document.id): document for document in await self.documents(value)}
        store = self.store(preview_id)
        notes = []
        for identifier in value["sources"]:
            run_id = store.run_id(identifier)
            output = await store.layers.get(UUID(identifier), run_id)
            if output is not None:
                await self.validate_result(store, value, documents[identifier], output)
            error = await store.read(f"error-{run_id}-{record.attempts}")
            notes.append(
                {
                    "document_id": identifier,
                    "status": "completed" if output else "failed" if error else "pending",
                    "error": error if not output else None,
                }
            )
        spec = await store.read("specification")
        return {
            "id": str(preview_id),
            "draft_id": value["request"]["draft_id"],
            "revision": value["request"]["revision"],
            "revision_hash": value["revision_hash"],
            "specification_hash": AxisSpecification.model_validate(
                spec["specification"]
            ).fingerprint
            if spec
            else None,
            "expires_at": value["expires_at"],
            "status": record.status,
            "stage": record.stage,
            "notes": notes,
            "error": {"code": record.error_code, "retryable": record.retryable}
            if record.error_code
            else None,
        }

    async def validate_result(self, store, value, document, output):
        saved = await store.read("specification")
        if saved is None:
            raise AxisError("axis_artifact_mismatch")
        spec = AxisSpecification.model_validate(saved["specification"])
        extractor = PersonalAxisExtractor(self.runtime.document_store, store.layers, spec)
        if output.request_config != extractor.request_config or output.profile != spec.profile:
            raise AxisError("axis_artifact_mismatch")
        if output.content_hash != value["sources"][str(document.id)]:
            raise AxisError("axis_source_changed")
        try:
            extractor.validate_output(output, document)
        except ValueError:
            raise AxisError("axis_artifact_invalid") from None

    async def results(self, preview_id):
        _, value = await self.live(preview_id)
        store = self.store(preview_id)
        async with self.source_guard(value, preview_id) as sources:
            documents = []
            for document in sources:
                run_id = store.run_id(document.id)
                output = await store.layers.get(document.id, run_id)
                findings = []
                if output:
                    await self.validate_result(store, value, document, output)
                    for index, item in enumerate(output.payload["findings"]):
                        finding = {**item, "id": f"AxisFinding:{uuid5(run_id, str(index))}"}
                        finding["evidence"] = [
                            {
                                "quote": e["quote"],
                                "start_char": document.content.index(e["quote"]),
                                "end_char": document.content.index(e["quote"]) + len(e["quote"]),
                            }
                            for e in item["evidence"]
                        ]
                        findings.append(finding)
                documents.append(
                    {
                        "document_id": str(document.id),
                        "run_id": str(run_id),
                        "source_hash": value["sources"][str(document.id)],
                        "title": document.title or "Nota",
                        "findings": findings,
                        "status": "completed" if output else "pending",
                        "warnings": output.payload.get("warnings", []) if output else [],
                    }
                )
            return {
                "preview": await self.snapshot(preview_id),
                "documents": documents,
                "graph": project_preview(preview_id, documents),
            }

    async def retry(self, preview_id, key):
        receipt = await self.receipt("axis_preview_retry", key)
        if receipt is not None:
            if receipt.resource_id != preview_id:
                raise AxisError("idempotency_conflict")
            return await self.snapshot(preview_id)
        async with self.guard(preview_id):
            record, value = await self.live(preview_id)
            await self.documents(value)
            async with self.processing.sessions.begin() as session:
                locked = await session.scalar(
                    select(
                        func.pg_try_advisory_xact_lock(
                            func.hashtextextended(f"{self.owner}:axis-retry:{key}", 0)
                        )
                    )
                )
                if not locked:
                    raise AxisError("axis_preview_busy")
                receipt = await session.scalar(
                    select(ProcessingReceipt).where(
                        ProcessingReceipt.user_id == self.owner,
                        ProcessingReceipt.operation == "axis_preview_retry",
                        ProcessingReceipt.key == key,
                    )
                )
                if receipt:
                    if receipt.resource_id != preview_id:
                        raise AxisError("idempotency_conflict")
                    return await self.snapshot(preview_id)
                if record.status == "failed" and not record.retryable:
                    raise AxisError("axis_preview_not_retryable")
                now = await session.scalar(select(func.clock_timestamp()))
                session.add(
                    ProcessingReceipt(
                        user_id=self.owner,
                        operation="axis_preview_retry",
                        key=key,
                        request_hash=str(preview_id),
                        resource_kind="axis_preview",
                        resource_id=preview_id,
                        config={},
                        manifest={},
                        processing_id=preview_id,
                        lease_token=uuid4(),
                        lease_expires_at=now,
                        accepted_at=now,
                        expires_at=record.expires_at,
                    )
                )
                if record.status != "failed":
                    return await self.snapshot(preview_id)
                current = await session.get(ProcessingRecord, record.id, with_for_update=True)
                current.status = "queued"
                current.error_code, current.retryable = None, False
                current.generation += 1
                current.version += 1
                current.stage_attempts = 0
                current.available_at = await session.scalar(select(func.clock_timestamp()))
                self.processing.schedule(session, current)
            return await self.snapshot(preview_id)

    async def accept(self, preview_id, revision_hash):
        async with self.guard(preview_id):
            approved = await self.axes.approved(self.owner, preview_id, revision_hash)
            if approved is not None:
                return approved
            record, value = await self.live(preview_id)
            if record.status != "completed" or record.stage != "done":
                raise AxisError("axis_preview_incomplete")
            if revision_hash != value["revision_hash"]:
                raise AxisError("axis_revision_conflict")
            async with self.source_guard(value, preview_id):
                snapshot = await self.snapshot(preview_id)
                if any(note["status"] != "completed" for note in snapshot["notes"]):
                    raise AxisError("axis_preview_incomplete")
                spec = await self.store(preview_id).read("specification")
                # Recheck expiry immediately before entering the approval transaction.
                await self.live(preview_id)
                return await self.axes.accept(
                    self.owner,
                    preview_id,
                    PreviewRequest.model_validate(value["request"]),
                    AxisSpecification.model_validate(spec["specification"]),
                    datetime.fromisoformat(value["expires_at"]),
                )
