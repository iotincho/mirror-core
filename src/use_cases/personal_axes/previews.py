"""Own the temporary evaluation and permanent approval boundaries of personal axes."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from src.core.documents.ports import DocumentNotFoundError, DocumentStore
from src.core.extractors.personal_axes.models import AxisError, AxisSpecification, PreviewRequest
from src.core.extractors.personal_axes.pagination import page
from src.core.extractors.personal_axes.preview_ports import (
    AxisApprovals,
    PreviewFiles,
    PreviewTransactions,
)
from src.core.extractors.personal_axes.previews import PreviewConfiguration, SampleSourceUnavailable
from src.use_cases.extraction.personal_axis import PersonalAxisExtractor
from src.use_cases.personal_axes.preview_projection import project_preview


class AxisPreviews:
    def __init__(
        self,
        owner,
        originals: DocumentStore,
        artifacts: PreviewFiles,
        persistence: PreviewTransactions,
        definitions: AxisApprovals,
        configuration: PreviewConfiguration,
        clock,
    ):
        self.owner, self.originals, self.artifacts = owner, originals, artifacts
        self.persistence, self.definitions = persistence, definitions
        self.configuration, self.clock = configuration, clock

    def store(self, preview_id):
        return self.artifacts.for_preview(preview_id)

    @asynccontextmanager
    async def guard(self, preview_id):
        async with self.persistence.guard(self.owner, preview_id) as locked:
            if not locked:
                raise AxisError("axis_preview_busy")
            yield

    @asynccontextmanager
    async def source_guard(self, value, preview_id):
        # One connection for the whole sample, not one per note (pool exhaustion).
        async with self.persistence.sources(
            self.owner, [UUID(identifier) for identifier in value["sources"]], shared=True
        ) as locked:
            if not locked:
                raise AxisError("axis_source_busy")
            yield await self.documents(value)

    async def documents(self, value):
        documents = []
        for identifier, expected in value["sources"].items():
            try:
                document = await self.originals.get(UUID(identifier))
            except DocumentNotFoundError:
                raise AxisError("axis_source_unavailable") from None
            from src.core.extractors.contracts import content_hash

            if content_hash(document.content) != expected:
                raise AxisError("axis_source_changed")
            documents.append(document)
        return documents

    async def live(self, preview_id):
        record = await self.persistence.get(self.owner, preview_id)
        if record is None or record.workflow != "axis_preview":
            raise AxisError("axis_preview_not_found")
        if record.resource_deleted:
            raise AxisError("axis_source_unavailable")
        if record.expires_at <= self.clock():
            raise AxisError("axis_preview_expired")
        value = await self.store(preview_id).read("input")
        if value is None:
            raise AxisError("axis_preview_not_found")
        if datetime.fromisoformat(value["expires_at"]) <= self.clock():
            raise AxisError("axis_preview_expired")
        return record, value

    async def receipt(self, operation, key):
        return await self.persistence.receipt(self.owner, operation, key)

    async def request(self, request: PreviewRequest, key: UUID):
        preview_id = uuid5(self.owner, f"axis-preview:{key}")
        store = self.store(preview_id)
        # Replays must also work while the worker holds the preview execution lock.
        receipt = await self.receipt("axis_preview", key)
        if receipt is not None:
            if receipt.request_hash != request.fingerprint:
                raise AxisError("idempotency_conflict")
            return await self.snapshot(preview_id)
        if await self.definitions.approved(self.owner, preview_id, request.fingerprint) is not None:
            raise AxisError("axis_preview_already_accepted")
        async with self.guard(preview_id):
            receipt = await self.receipt("axis_preview", key)
            if receipt is not None:
                if receipt.request_hash != request.fingerprint:
                    raise AxisError("idempotency_conflict")
                return await self.snapshot(preview_id)
            if request.axis_id:
                axis = await self.definitions.get(self.owner, request.axis_id)
                if axis.current_version_id != request.base_version_id:
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
            configuration = self.configuration.extraction()
            if request.mode == "repeat":
                configuration = {key: previous[key] for key in configuration}
            if not configuration["model"] or configuration["provider"] != "openai":
                raise AxisError("axis_provider_configuration")
            old = await store.read("input")
            if old is not None and old["revision_hash"] != request.fingerprint:
                raise AxisError("idempotency_conflict")
            async with self.persistence.sources(self.owner, request.document_ids) as locked:
                if not locked:
                    raise AxisError("axis_source_busy")
                from src.core.extractors.contracts import content_hash

                sources = {}
                for identifier in request.document_ids:
                    try:
                        document = await self.originals.get(identifier)
                    except DocumentNotFoundError:
                        raise SampleSourceUnavailable() from None
                    if len(document.content) > configuration["max_input_chars"]:
                        raise AxisError("axis_input_too_long")
                    sources[str(identifier)] = content_hash(document.content)
                if request.previous_preview_id and not request.change_sample:
                    if sources != prior["sources"]:
                        raise AxisError("axis_source_changed")
                async with self.persistence.reservation(
                    self.owner, self.configuration.max_pending
                ) as reservation:
                    now = reservation.now
                    value = old or {
                        "request": request.model_dump(mode="json"),
                        "revision_hash": request.fingerprint,
                        "sources": sources,
                        "configuration": configuration,
                        "previous_specification": previous,
                        "expires_at": (
                            now + timedelta(hours=self.configuration.ttl_hours)
                        ).isoformat(),
                    }
                    if datetime.fromisoformat(value["expires_at"]) <= now:
                        raise AxisError("axis_preview_expired")
                    if value["sources"] != sources:
                        raise AxisError("axis_source_changed")
                    # Files precede executable SQL/outbox. An interrupted transaction leaves
                    # an immutable, deterministic orphan; a replay can reuse it safely.
                    await store.write("input", value)
                    await reservation.enqueue(
                        preview_id,
                        key,
                        request.fingerprint,
                        sources,
                        datetime.fromisoformat(value["expires_at"]),
                    )
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
        extractor = PersonalAxisExtractor(self.originals, store.layers, spec)
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
            async with self.persistence.retrying(self.owner, key) as transaction:
                receipt = transaction.receipt
                if receipt:
                    if receipt.resource_id != preview_id:
                        raise AxisError("idempotency_conflict")
                    return await self.snapshot(preview_id)
                if record.status == "failed" and not record.retryable:
                    raise AxisError("axis_preview_not_retryable")
                await transaction.record(record, key)
            return await self.snapshot(preview_id)

    async def accept(self, preview_id, revision_hash):
        async with self.guard(preview_id):
            approved = await self.definitions.approved(self.owner, preview_id, revision_hash)
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
                return await self.definitions.accept(
                    self.owner,
                    preview_id,
                    PreviewRequest.model_validate(value["request"]),
                    AxisSpecification.model_validate(spec["specification"]),
                    datetime.fromisoformat(value["expires_at"]),
                )

    async def preview_neighbors(self, preview_id, node_id=None, cursor=None, limit=30):
        results = await self.results(preview_id)
        graph = results["graph"]
        root = node_id or graph["root_id"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        if root not in nodes:
            raise AxisError("axis_node_not_found")
        revision = results["preview"]["revision_hash"]
        scope = [str(self.owner), str(preview_id), revision, root]
        adjacent = [e for e in graph["edges"] if root in (e["source"], e["target"])]
        neighbors = {e["target"] if e["source"] == root else e["source"] for e in adjacent}
        chosen, following = page(list(neighbors), scope, cursor, limit, lambda item: item)
        visible = set(chosen) | {root}
        # A page counts direct neighbors; finding context is bounded by the payload contract.
        finding_ids = {n for n in visible if nodes[n]["type"] == "AxisFinding"}
        for edge in graph["edges"]:
            if edge["type"] in {"HAS_FINDING", "HAS_TAG"} and (
                edge["source"] in finding_ids or edge["target"] in finding_ids
            ):
                visible.update((edge["source"], edge["target"]))
        return {
            "preview_id": str(preview_id),
            "revision_hash": revision,
            "root_id": root,
            "nodes": [nodes[n] for n in sorted(visible)],
            "edges": [
                e for e in graph["edges"] if e["source"] in visible and e["target"] in visible
            ],
            "next_cursor": following,
            "limit": limit,
        }
