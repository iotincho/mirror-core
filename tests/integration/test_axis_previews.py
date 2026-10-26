"""The full creation/approval boundary against an isolated migrated PostgreSQL."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.access.api.public.personal_axes.errors import axis_status
from src.adapters.access.api.public.personal_axes.responses import axis_response
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.models import (
    ProcessingEvent,
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.adapters.storage.postgres.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.bootstrap.auth import require_authenticated
from src.bootstrap.personal_axes_dependencies import get_preview_cases
from src.bootstrap.personal_axes_previews import (
    build_axis_previews,
    build_preview_workflow,
    configuration,
    expire_axis_previews,
)
from src.bootstrap.personal_axes_reads import build_axis_definitions, get_axis_definitions
from src.bootstrap.processing import build_executor as ExecuteProcessing
from src.bootstrap.public_api import app
from src.bootstrap.settings import Settings
from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.contracts import ProviderMetadata
from src.core.extractors.personal_axes.models import (
    AxisError,
    Criterion,
    FindingsResponse,
    PreviewRequest,
)
from src.core.processing.errors import StorageUnavailable
from src.core.processing.workflows import WorkflowRegistry

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Provider:
    def __init__(self):
        self.generations = []
        self.calls = {}
        self.fail_once = None
        self.empty = False

    async def generate_criterion(self, data):
        self.generations.append(data)
        return Criterion(instructions=data["purpose"] + " " + " ".join(data["adjustments"])), None

    async def extract(self, document, profile):
        self.calls[document.id] = self.calls.get(document.id, 0) + 1
        if self.fail_once == document.id:
            self.fail_once = None
            raise ConnectionError("synthetic provider failure")
        return FindingsResponse(
            findings=[]
            if self.empty
            else [
                {
                    "title": "Idea de episodio",
                    "content": "Desarrollo para retomar la idea.",
                    "evidence": [{"quote": document.content}],
                    "tags": ["podcast", "creación"],
                }
            ]
        ), ProviderMetadata(provider="test", model="test")


@pytest.fixture
async def laboratory(tmp_path):
    engine = create_async_engine(
        os.environ["PROCESSING_TEST_DATABASE_URL"],
        hide_parameters=True,
        pool_size=8,
        max_overflow=0,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owners = [uuid4(), uuid4()]
    async with sessions.begin() as session:
        for owner in owners:
            session.add(User(id=owner, email=f"{owner}@test.local", hashed_password="unused"))
            await session.flush()
            session.add(
                UserWorkspace(
                    user_id=owner,
                    status="active",
                    arcadedb_instance_key="test",
                    database_name=f"axis_{owner.hex}",
                    graph_username=f"axis_{owner.hex}",
                    graph_secret_ciphertext="unused",
                )
            )
    settings = Settings(
        _env_file=None,
        PERSONAL_AXES_ENABLED=True,
        OPENAI_MODEL="test-model",
        WORKSPACES_PATH=tmp_path,
        PERSONAL_AXES_MAX_PENDING_PREVIEWS=20,
    )
    processing = ProcessingRepository(sessions, lease_seconds=3)
    runtimes = {
        owner: SimpleNamespace(
            context=SimpleNamespace(user_id=owner, filesystem_root=tmp_path / str(owner)),
            document_store=FileDocumentStore(tmp_path / str(owner) / "documents"),
        )
        for owner in owners
    }
    documents = []
    for index in range(6):
        document = build_document(NewDocument(content=f"Idea {index}: quiero crear un podcast."))
        await runtimes[owners[0]].document_store.save(document)
        documents.append(document)
    provider = Provider()

    @asynccontextmanager
    async def runtime(owner):
        yield runtimes[owner]

    registry = WorkflowRegistry()
    registry.register(
        "axis_preview",
        1,
        build_preview_workflow(
            runtime, lambda config: provider, settings, repository=processing
        ).definition,
    )
    lab = SimpleNamespace(
        sessions=sessions,
        processing=processing,
        owners=owners,
        runtimes=runtimes,
        provider=provider,
        documents=documents,
        settings=settings,
        service=build_axis_previews(processing, runtimes[owners[0]], settings),
        other=build_axis_previews(processing, runtimes[owners[1]], settings),
        execute=ExecuteProcessing(processing, registry),
    )
    try:
        yield lab
    finally:
        app.dependency_overrides.clear()
        async with sessions.begin() as session:
            await session.execute(
                delete(ProcessingReceipt).where(ProcessingReceipt.user_id.in_(owners))
            )
            ids = select(ProcessingRecord.id).where(ProcessingRecord.user_id.in_(owners))
            await session.execute(
                delete(ProcessingOutbox).where(ProcessingOutbox.processing_id.in_(ids))
            )
            await session.execute(
                delete(ProcessingRecord).where(ProcessingRecord.user_id.in_(owners))
            )
            await session.execute(delete(User).where(User.id.in_(owners)))
        await engine.dispose()


def request(lab, **changes):
    data = {
        "draft_id": uuid4(),
        "revision": 1,
        "title": "Ideas",
        "purpose": "Ideas para podcast",
        "document_ids": [document.id for document in lab.documents[:5]],
        **changes,
    }
    return PreviewRequest.model_validate(data)


async def run(lab, preview):
    record = await lab.processing.get(UUID(preview["id"]), lab.owners[0])
    await lab.execute(record.id, record.generation)
    return await lab.service.snapshot(record.id)


async def test_full_http_refinement_exact_approval_and_no_document_events(laboratory):
    lab = laboratory
    app.dependency_overrides[require_authenticated] = lambda: None
    app.dependency_overrides[get_preview_cases] = lambda: lab.service
    app.dependency_overrides[get_axis_definitions] = lambda: build_axis_definitions(
        lab.sessions, lab.service.owner
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        original = request(lab)
        key = str(uuid4())
        created = await client.post(
            "/laboratory/axis-previews",
            json=original.model_dump(mode="json"),
            headers={"Idempotency-Key": key},
        )
        assert created.status_code == 202, created.text
        first = await run(lab, created.json())
        assert first["status"] == "completed"
        results = await client.get(f"/laboratory/axis-previews/{first['id']}/results")
        assert results.status_code == 200, results.text
        assert len(results.json()["documents"]) == 5
        root_page = await client.get(
            f"/laboratory/axis-previews/{first['id']}/neighbors", params={"limit": 2}
        )
        assert root_page.status_code == 200, root_page.text
        branch = root_page.json()
        assert len(branch["nodes"]) == 3 and len(branch["edges"]) == 2
        assert branch["next_cursor"] and branch["revision_hash"] == first["revision_hash"]
        another = await client.get(
            f"/laboratory/axis-previews/{first['id']}/neighbors",
            params={"cursor": branch["next_cursor"], "limit": 2},
        )
        assert another.status_code == 200
        assert {n["id"] for n in branch["nodes"][1:]} != {
            n["id"] for n in another.json()["nodes"][1:]
        }
        note_id = next(n["id"] for n in branch["nodes"] if n["type"] == "Document")
        note_branch = await client.get(
            f"/laboratory/axis-previews/{first['id']}/neighbors", params={"node_id": note_id}
        )
        assert any(e["quote"] for e in note_branch.json()["edges"] if e["type"] == "HAS_FINDING")
        assert (
            await client.get(
                f"/laboratory/axis-previews/{first['id']}/neighbors",
                params={"node_id": note_id, "cursor": branch["next_cursor"]},
            )
        ).status_code == 422
        evidence_edges = [
            edge for edge in results.json()["graph"]["edges"] if edge["type"] == "HAS_FINDING"
        ]
        assert len(evidence_edges) == 5
        sources = {f"Document:{document.id}": document.content for document in lab.documents}
        for edge in evidence_edges:
            assert sources[edge["source"]][edge["start_char"] : edge["end_char"]] == edge["quote"]
        assert all(
            not {"quote", "evidence", "evidence_json", "start_char", "end_char"} & node.keys()
            for node in results.json()["graph"]["nodes"]
        )
        assert (
            len(
                [
                    node
                    for node in results.json()["graph"]["nodes"]
                    if node["type"] == "AxisTagGroup"
                ]
            )
            == 2
        )
        replay = await client.post(
            "/laboratory/axis-previews",
            json=original.model_dump(mode="json"),
            headers={"Idempotency-Key": key},
        )
        assert replay.json()["id"] == first["id"]
        refined = request(
            lab,
            **{
                **original.model_dump(),
                "revision": 2,
                "mode": "refine",
                "previous_preview_id": first["id"],
                "adjustments": ["Más desarrollo"],
            },
        )
        second = await lab.service.request(refined, uuid4())
        second = await run(lab, second)
        assert second["status"] == "completed"
        assert second["specification_hash"] != first["specification_hash"]
        assert lab.provider.generations[1]["previous_instructions"]
        async with lab.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(PersonalAxis)) == 0
        accepted = await client.post(
            f"/laboratory/axis-previews/{second['id']}/accept",
            json={"revision_hash": second["revision_hash"]},
        )
        assert accepted.status_code == 200, accepted.text
        axis = accepted.json()
        saved = await lab.service.store(UUID(second["id"])).read("specification")
        assert axis["version"]["specification"] == saved["specification"]
        assert axis["version"]["number"] == 1
        assert axis["version"]["specification_hash"] == second["specification_hash"]
        assert len(lab.provider.generations) == 2 and sum(lab.provider.calls.values()) == 10
        assert (await client.get("/personal-axes")).json()["items"][0]["id"] == axis["id"]
        path = f"/personal-axes/{axis['id']}"
        assert (await client.get(path)).json() == axis
        assert (await client.get(f"{path}/versions/{axis['current_version_id']}")).json() == axis
        assert (await client.get(f"{path}/versions/{uuid4()}")).status_code == 404
        paused = await client.patch(path, json={"enabled": False})
        assert paused.status_code == 200 and paused.json()["enabled"] is False
        assert paused.json()["version"] == axis["version"]
        app.dependency_overrides[get_axis_definitions] = lambda: build_axis_definitions(
            lab.sessions, lab.owners[1]
        )
        assert (await client.get("/personal-axes")).json()["items"] == []
        assert (await client.get(path)).json() == {"detail": "axis_not_found"}
        assert (
            await client.get(f"{path}/versions/{axis['current_version_id']}")
        ).status_code == 404
        assert (await client.patch(path, json={"enabled": True})).status_code == 404
    async with lab.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingEvent)
                .where(ProcessingEvent.user_id.in_(lab.owners))
            )
            == 0
        )
    assert await lab.processing.list_for_owner(lab.owners[0]) == []


async def test_partial_failure_retry_only_missing_note_and_key_is_idempotent(laboratory):
    lab = laboratory
    lab.provider.fail_once = lab.documents[2].id
    preview = await lab.service.request(request(lab), uuid4())
    partial = await run(lab, preview)
    assert partial["status"] == "retrying"
    assert [item["status"] for item in partial["notes"]].count("completed") == 4
    with pytest.raises(AxisError, match="incomplete"):
        axis_response(await lab.service.accept(UUID(preview["id"]), preview["revision_hash"]))
    async with lab.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == UUID(preview["id"]))
            .values(status="failed", retryable=True)
        )
    key = uuid4()
    retried = await lab.service.retry(UUID(preview["id"]), key)
    completed = await run(lab, retried)
    assert completed["status"] == "completed"
    assert sum(lab.provider.calls.values()) == 6 and len(lab.provider.generations) == 1
    assert await lab.service.retry(UUID(preview["id"]), key) == completed


async def test_empty_sample_can_be_accepted_and_repeat_keeps_specification(laboratory):
    lab = laboratory
    lab.provider.empty = True
    original = request(lab)
    first = await run(lab, await lab.service.request(original, uuid4()))
    lab.settings.openai_model = None  # Repeating freezes the complete evaluated configuration.
    lab.service.configuration = configuration(lab.settings)
    repeated = request(
        lab,
        **{
            **original.model_dump(),
            "revision": 2,
            "mode": "repeat",
            "previous_preview_id": first["id"],
        },
    )
    second = await run(lab, await lab.service.request(repeated, uuid4()))
    assert first["specification_hash"] == second["specification_hash"]
    assert len(lab.provider.generations) == 1
    results = await lab.service.results(UUID(second["id"]))
    assert all(not item["findings"] for item in results["documents"])
    assert len(results["graph"]["nodes"]) == 6  # Root plus five isolated sample notes.
    accepted = axis_response(await lab.service.accept(UUID(second["id"]), second["revision_hash"]))
    assert accepted["version"]["number"] == 1


async def test_expiry_cleanup_and_lost_approval_response(laboratory):
    lab = laboratory
    completed = await run(lab, await lab.service.request(request(lab), uuid4()))
    identifier = UUID(completed["id"])
    accepted = axis_response(await lab.service.accept(identifier, completed["revision_hash"]))
    async with lab.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == identifier)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with pytest.raises(AxisError) as expired:
        await lab.service.snapshot(identifier)
    assert axis_status(expired.value) == 410
    await expire_axis_previews(lab.processing, lab.settings)
    assert not lab.service.store(identifier).root.exists()
    assert await lab.processing.get(identifier, lab.owners[0]) is None
    assert (
        axis_response(await lab.service.accept(identifier, completed["revision_hash"])) == accepted
    )
    await lab.execute(identifier, 1)  # A late broker message cannot resurrect deleted state.
    assert not lab.service.store(identifier).root.exists()


async def test_cross_user_ids_are_not_authority_and_samples_change_explicitly(laboratory):
    lab = laboratory
    original = request(lab)
    first = await run(lab, await lab.service.request(original, uuid4()))
    for operation in (
        lab.other.snapshot(UUID(first["id"])),
        lab.other.results(UUID(first["id"])),
        lab.other.accept(UUID(first["id"]), first["revision_hash"]),
    ):
        with pytest.raises(AxisError) as unknown:
            await operation
        assert axis_status(unknown.value) == 404
    with pytest.raises(AxisError):
        await lab.other.request(original, uuid4())
    changed = request(
        lab,
        **{
            **original.model_dump(),
            "revision": 2,
            "mode": "refine",
            "previous_preview_id": first["id"],
            "document_ids": [doc.id for doc in lab.documents[1:]],
        },
    )
    with pytest.raises(AxisError, match="sample_change_required"):
        await lab.service.request(changed, uuid4())
    explicit = changed.model_copy(update={"change_sample": True})
    assert (await run(lab, await lab.service.request(explicit, uuid4())))["status"] == "completed"


async def test_source_deletion_invalidates_preview_and_cleanup(laboratory):
    lab = laboratory
    completed = await run(lab, await lab.service.request(request(lab), uuid4()))
    identifier = UUID(completed["id"])
    await lab.processing.mark_deleted(lab.owners[0], lab.documents[0].id)
    await lab.runtimes[lab.owners[0]].document_store.delete(lab.documents[0].id)
    with pytest.raises(AxisError, match="source_unavailable"):
        axis_response(await lab.service.accept(identifier, completed["revision_hash"]))
    await expire_axis_previews(lab.processing, lab.settings)
    assert not lab.service.store(identifier).root.exists()


async def test_approval_version_conflict_and_database_immutability(laboratory):
    lab = laboratory
    original = await run(lab, await lab.service.request(request(lab), uuid4()))
    axis = axis_response(await lab.service.accept(UUID(original["id"]), original["revision_hash"]))
    requests = [
        request(
            lab,
            axis_id=axis["id"],
            base_version_id=axis["version"]["id"],
            purpose=f"Nueva finalidad {index}",
        )
        for index in range(2)
    ]
    previews = [await run(lab, await lab.service.request(item, uuid4())) for item in requests]
    approved = axis_response(
        await lab.service.accept(UUID(previews[0]["id"]), previews[0]["revision_hash"])
    )
    assert approved["version"]["number"] == 2
    with pytest.raises(AxisError, match="base_version_conflict"):
        axis_response(
            await lab.service.accept(UUID(previews[1]["id"]), previews[1]["revision_hash"])
        )
    with pytest.raises(DBAPIError):
        async with lab.sessions.begin() as session:
            await session.execute(
                update(PersonalAxisVersion)
                .where(PersonalAxisVersion.id == UUID(axis["version"]["id"]))
                .values(purpose="overwrite")
            )
    with pytest.raises(IntegrityError):
        async with lab.sessions.begin() as session:
            other = PersonalAxis(
                id=uuid4(),
                user_id=lab.owners[0],
                current_version_id=UUID(axis["version"]["id"]),
                enabled=True,
            )
            session.add(other)


async def test_interrupted_enqueue_reuses_orphan_input_and_config(laboratory, monkeypatch):
    lab = laboratory
    original, key = request(lab), uuid4()
    schedule = lab.processing.schedule

    def interrupted(*args):
        raise ConnectionError("synthetic enqueue interruption")

    monkeypatch.setattr(lab.processing, "schedule", interrupted)
    with pytest.raises(ConnectionError):
        await lab.service.request(original, key)
    monkeypatch.setattr(lab.processing, "schedule", schedule)
    lab.settings.openai_model = "changed-after-interruption"
    lab.service.configuration = configuration(lab.settings)
    completed = await run(lab, await lab.service.request(original, key))
    saved = await lab.service.store(UUID(completed["id"])).read("specification")
    assert saved["specification"]["model"] == "test-model"
    assert completed["status"] == "completed"


async def test_replay_and_expiry_while_worker_holds_execution_lock(laboratory):
    lab = laboratory
    started, release = asyncio.Event(), asyncio.Event()
    generate = lab.provider.generate_criterion

    async def blocked(data):
        started.set()
        await release.wait()
        return await generate(data)

    lab.provider.generate_criterion = blocked
    original, key = request(lab), uuid4()
    preview = await lab.service.request(original, key)
    identifier = UUID(preview["id"])
    task = asyncio.create_task(lab.execute(identifier, 1))
    try:
        await asyncio.wait_for(started.wait(), 3)
        replay = await asyncio.wait_for(lab.service.request(original, key), 3)
        assert replay["id"] == preview["id"] and replay["status"] == "running"
        async with lab.sessions.begin() as session:
            await session.execute(
                update(ProcessingRecord)
                .where(ProcessingRecord.id == identifier)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        await expire_axis_previews(lab.processing, lab.settings)
        assert lab.service.store(identifier).root.exists()
        release.set()
        await asyncio.wait_for(task, 3)
        record = await lab.processing.get(identifier, lab.owners[0])
        assert record.status == "failed" and record.error_code == "axis_preview_expired"
        assert await lab.service.store(identifier).read("specification") is None
        await expire_axis_previews(lab.processing, lab.settings)
        assert not lab.service.store(identifier).root.exists()
    finally:
        release.set()
        await task


async def test_changed_request_key_and_stale_revision_never_create_an_axis(laboratory):
    lab = laboratory
    original, key = request(lab), uuid4()
    first = await run(lab, await lab.service.request(original, key))
    with pytest.raises(AxisError, match="idempotency_conflict"):
        await lab.service.request(original.model_copy(update={"purpose": "otra finalidad"}), key)
    with pytest.raises(AxisError, match="revision_conflict"):
        axis_response(await lab.service.accept(UUID(first["id"]), "a" * 64))
    async with lab.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PersonalAxis)) == 0


async def test_source_locks_exclude_deletion_without_exhausting_small_pool(laboratory):
    lab = laboratory
    first = await run(lab, await lab.service.request(request(lab), uuid4()))
    identifier = UUID(first["id"])
    _, value = await lab.service.live(identifier)
    async with lab.service.source_guard(value, identifier):
        for document in lab.documents[:5]:
            async with lab.processing.lock_resource(lab.owners[0], document.id) as locked:
                assert not locked
    async with lab.processing.lock_resource(lab.owners[0], lab.documents[0].id) as locked:
        assert locked
        with pytest.raises(AxisError, match="source_busy"):
            axis_response(await lab.service.accept(identifier, first["revision_hash"]))
    assert (axis_response(await lab.service.accept(identifier, first["revision_hash"])))["version"][
        "number"
    ] == 1


async def test_generation_failure_does_not_log_private_provider_payload(laboratory, caplog):
    lab = laboratory

    async def rejected(data):
        raise ValueError("private-criterion-and-source-payload")

    lab.provider.generate_criterion = rejected
    preview = await lab.service.request(request(lab), uuid4())
    result = await run(lab, preview)
    assert result["status"] == "failed"
    assert "private-criterion-and-source-payload" not in caplog.text


async def test_modified_source_requires_explicit_new_sample(laboratory):
    lab = laboratory
    original = request(lab)
    first = await run(lab, await lab.service.request(original, uuid4()))
    document = lab.documents[0]
    changed = document.model_copy(update={"content": "Otra idea para el podcast."})
    path = lab.runtimes[lab.owners[0]].context.filesystem_root / "documents" / f"{document.id}.json"
    path.write_text(changed.model_dump_json(), encoding="utf-8")
    with pytest.raises(AxisError, match="source_changed"):
        axis_response(await lab.service.accept(UUID(first["id"]), first["revision_hash"]))
    refinement = original.model_copy(
        update={"revision": 2, "mode": "refine", "previous_preview_id": UUID(first["id"])}
    )
    with pytest.raises(AxisError, match="source_changed"):
        await lab.service.request(refinement, uuid4())
    explicit = refinement.model_copy(update={"change_sample": True})
    assert (await run(lab, await lab.service.request(explicit, uuid4())))["status"] == "completed"


async def test_refinement_keeps_the_complete_temporary_adjustment_history(laboratory):
    lab = laboratory
    original = request(lab, adjustments=["Conservar desarrollo"])
    first = await run(lab, await lab.service.request(original, uuid4()))
    refinement = original.model_copy(
        update={
            "revision": 2,
            "mode": "refine",
            "previous_preview_id": UUID(first["id"]),
            "adjustments": ["Sólo el comentario nuevo"],
        }
    )
    with pytest.raises(AxisError, match="adjustment_history_required"):
        await lab.service.request(refinement, uuid4())
    complete = refinement.model_copy(
        update={"adjustments": ["Conservar desarrollo", "Separar propuestas independientes"]}
    )
    assert (await run(lab, await lab.service.request(complete, uuid4())))["status"] == "completed"
    assert lab.provider.generations[-1]["adjustments"] == complete.adjustments


async def test_database_interruption_preserves_lease_and_prompt_checkpoint(laboratory, monkeypatch):
    lab = laboratory
    from src.use_cases.personal_axes.previews import AxisPreviews as PreviewCase

    original = PreviewCase.source_guard
    interrupted = False

    @asynccontextmanager
    async def source_guard(self, value, preview_id):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            cause = OperationalError("synthetic", {}, Exception("database unavailable"))
            raise StorageUnavailable("processing_storage_unavailable") from cause
        async with original(self, value, preview_id) as documents:
            yield documents

    monkeypatch.setattr(PreviewCase, "source_guard", source_guard)
    preview = await lab.service.request(request(lab), uuid4())
    identifier = UUID(preview["id"])
    with pytest.raises(StorageUnavailable) as failure:
        await lab.execute(identifier, 1)
    assert isinstance(failure.value.__cause__, OperationalError)
    record = await lab.processing.get(identifier, lab.owners[0])
    assert record.status == "running" and record.stage == "sample_extraction"
    assert await lab.service.store(identifier).read("specification") is not None
    async with lab.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == identifier)
            .values(lease_expires_at=func.clock_timestamp())
        )
    await lab.processing.recover()
    assert (await run(lab, preview))["status"] == "completed"
    assert len(lab.provider.generations) == 1


async def test_concurrent_preview_quota_commits_one_receipt_job_and_outbox(laboratory):
    lab = laboratory
    lab.settings.personal_axes_max_pending_previews = 1
    lab.service.configuration = configuration(lab.settings)
    requests = [request(lab, document_ids=[document.id]) for document in lab.documents[:2]]
    results = await asyncio.gather(
        *(lab.service.request(body, uuid4()) for body in requests), return_exceptions=True
    )
    accepted = [result for result in results if isinstance(result, dict)]
    rejected = [result for result in results if isinstance(result, AxisError)]
    assert len(accepted) == len(rejected) == 1
    assert rejected[0].code == "axis_preview_limit" and axis_status(rejected[0]) == 429
    async with lab.sessions() as session:
        for model in (ProcessingRecord, ProcessingReceipt):
            assert (
                await session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == lab.owners[0])
                )
                == 1
            )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingOutbox)
                .where(ProcessingOutbox.processing_id == UUID(accepted[0]["id"]))
            )
            == 1
        )
    assert not lab.provider.generations and not lab.provider.calls
