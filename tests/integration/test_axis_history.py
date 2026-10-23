"""History batches through real SQL, extractor artifacts and ArcadeDB transactions."""

# ruff: noqa: F811
import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run  # noqa: F401
from test_personal_axis_processing import active, approve  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.domain.documents import NewDocument, build_document
from src.extractors.contracts import content_hash
from src.extractors.personal_axes.contracts import AxisError, AxisSpecification
from src.extractors.personal_axes.history import AxisHistory
from src.extractors.personal_axes.history_models import AxisHistoryBatch, AxisHistoryItem
from src.extractors.personal_axes.history_schemas import HistoryRequest
from src.extractors.personal_axes.models import PersonalAxisVersion
from src.extractors.personal_axes.prompt_builder import VOICE_RULES
from src.processing.execution import ExecuteProcessing, WorkflowFailure
from src.processing.models import ProcessingEvent, ProcessingRecord
from src.use_cases.process_axis_history import ProcessAxisHistory

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.getenv("PROCESSING_TEST_DATABASE_URL") and os.getenv("EMOTIONS_TEST_ARCADEDB_URL")),
        reason="requires disposable PostgreSQL and ArcadeDB",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def history(active):
    env = active
    env.history = AxisHistory(env.previews)
    legacy = env.registry.definitions[("document", 3)].run.__self__
    factory = env.registry.definitions[("extractor", 1)].run.__self__.extractor_factory
    env.history_worker = ProcessAxisHistory(legacy.runtime_factory, factory)
    env.registry.register("axis_history_note", 1, env.history_worker.definition)
    try:
        yield env
    finally:
        async with env.repo.sessions.begin() as session:
            await session.execute(
                delete(AxisHistoryBatch).where(AxisHistoryBatch.user_id == env.owner)
            )


async def source(env, title="Otra nota"):
    document = build_document(NewDocument(content=env.original.content)).model_copy(
        update={"title": title}
    )
    await env.runtime.document_store.save(document)
    return document


def request(axis, documents):
    return HistoryRequest(
        version_id=axis["current_version_id"],
        documents=[
            {"document_id": document.id, "source_hash": content_hash(document.content)}
            for document in documents
        ],
    )


async def jobs(env, batch):
    async with env.repo.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(ProcessingRecord)
                    .join(AxisHistoryItem, AxisHistoryItem.processing_id == ProcessingRecord.id)
                    .where(AxisHistoryItem.batch_id == UUID(str(batch["id"])))
                    .order_by(ProcessingRecord.resource_id)
                )
            ).all()
        )


async def test_history_is_pinned_idempotent_isolated_and_counts_empty_results(history):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    await env.axes.set_enabled(env.owner, id, False)
    documents = [env.original, await source(env)]
    body, key = request(axis, documents), uuid4()
    before = await env.history.notes(id)
    assert before["remaining"] == 2
    batch = await env.history.start(id, body, key)
    assert (await env.history.start(id, body, key))["id"] == batch["id"]
    with pytest.raises(AxisError, match="request_conflict"):
        await env.history.start(id, request(axis, documents[:1]), key)
    for job in await jobs(env, batch):
        assert job.workflow == "axis_history_note"
        assert (await run(env, job)).status == "completed"
    result = await env.history.snapshot(id, batch["id"])
    assert result["status"] == "completed"
    assert result["counts"] == {"completed": 2}
    assert (await env.history.notes(id))["remaining"] == 0
    assert (await env.axes.get(env.owner, id))["enabled"] is False
    duplicate = await env.history.start(id, body, uuid4())
    assert duplicate["counts"] == {"skipped": 2}
    assert not await jobs(env, duplicate)
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingEvent)
                .where(
                    ProcessingEvent.processing_id.in_([job.id for job in await jobs(env, batch)])
                )
            )
            == 0
        )
    assert not any(
        job.workflow == "axis_history_note" for job in await env.repo.list_for_owner(env.owner)
    )
    # An empty extraction remains a completed, covered note, not an invitation to pay again.
    empty_axis = await approve(env, "Sin coincidencias")
    empty_id = UUID(empty_axis["id"])
    env.empty.add(empty_axis["version"]["specification"]["profile"]["id"])
    empty = await env.history.start(empty_id, request(empty_axis, documents[:1]), uuid4())
    await run(env, (await jobs(env, empty))[0])
    note = (await env.history.notes(empty_id))["items"]
    completed = next(row for row in note if row["document_id"] == documents[0].id)
    assert completed["status"] == "current" and completed["findings_count"] == 0


async def test_development_prompt_update_reanalyses_same_version_without_changing_source(history):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    body = request(axis, [env.original])
    first = await env.history.start(id, body, uuid4())
    await run(env, (await jobs(env, first))[0])
    assert (await env.history.notes(id))["remaining"] == 0
    old_profile = (await env.history.coverage(id))[str(env.original.id)]["profile_hash"]
    # The development owner explicitly permits editing their sole accepted definition in place.
    async with env.repo.sessions.begin() as session:
        await session.execute(
            text("ALTER TABLE personal_axis_versions DISABLE TRIGGER axis_version_immutable")
        )
        version = await session.get(PersonalAxisVersion, UUID(axis["current_version_id"]))
        spec = AxisSpecification.model_validate(version.specification)
        spec = spec.model_copy(
            update={
                "profile": spec.profile.model_copy(
                    update={"instructions": VOICE_RULES + spec.profile.instructions}
                )
            }
        )
        version.specification = spec.model_dump(mode="json")
        version.specification_hash = spec.fingerprint
        await session.flush()
        await session.execute(
            text("ALTER TABLE personal_axis_versions ENABLE TRIGGER axis_version_immutable")
        )
    notes = await env.history.notes(id)
    assert notes["remaining"] == 1 and notes["items"][0]["status"] == "unanalysed"
    second = await env.history.start(id, body, uuid4())
    queued = await jobs(env, second)
    assert len(queued) == 1
    assert (await run(env, queued[0])).status == "completed"
    assert (await env.history.snapshot(id, second["id"]))["counts"] == {"completed": 1}
    updated = (await env.history.coverage(id))[str(env.original.id)]
    assert updated["version_id"] == axis["current_version_id"]
    assert updated["profile_hash"] == spec.profile.fingerprint != old_profile
    assert (await env.history.notes(id))["remaining"] == 0
    assert sum(env.calls.values()) == 2
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                text("SELECT tgenabled::text FROM pg_trigger WHERE tgname='axis_version_immutable'")
            )
            == "O"
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PersonalAxisVersion)
                .where(PersonalAxisVersion.axis_id == id)
            )
            == 1
        )


async def test_stop_excludes_unstarted_notes_and_preserves_running_work(history):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    batch = await env.history.start(
        id, request(axis, [env.original, await source(env), await source(env)]), uuid4()
    )
    entered, release = asyncio.Event(), asyncio.Event()
    factory = env.history_worker.extractor_factory

    def gated(runtime, spec, *, extracting):
        extractor = factory(runtime, spec, extracting=extracting)
        if extracting:
            original = extractor.provider.extract

            async def extract(document, profile):
                entered.set()
                await release.wait()
                return await original(document, profile)

            extractor.provider.extract = extract
        return extractor

    env.history_worker.extractor_factory = gated
    records = await jobs(env, batch)
    running = asyncio.create_task(run(env, records[0]))
    await asyncio.wait_for(entered.wait(), 10)
    stopped = await env.history.stop(id, batch["id"])
    assert stopped["counts"]["stopped"] == 2
    assert stopped["counts"]["running"] == 1
    for job in records[1:]:
        await env.repo.assert_inactive(env.owner, job.resource_id)
    release.set()
    assert (await running).status == "completed"
    for job in records[1:]:
        await run(env, job)
    final = await env.history.snapshot(id, batch["id"])
    assert final["status"] == "stopped"
    assert final["counts"] == {"completed": 1, "stopped": 2}
    assert sum(env.calls.values()) == 1
    assert (await env.history.stop(id, batch["id"]))["counts"] == final["counts"]


async def test_failures_retry_only_failed_notes_and_source_changes_are_not_overwritten(history):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    doc = await source(env)
    batch = await env.history.start(id, request(axis, [env.original, doc]), uuid4())
    records = await jobs(env, batch)
    await run(env, records[0])
    env.fail.add(axis["version"]["specification"]["profile"]["id"])
    await ExecuteProcessing(env.repo, env.registry, max_attempts=1)(
        records[1].id, records[1].generation
    )
    failed = await env.history.snapshot(id, batch["id"])
    assert failed["counts"] == {"completed": 1, "failed": 1}
    assert failed["retryable"] == 1
    retry_key = uuid4()
    await env.history.retry(id, batch["id"], retry_key)
    queued = await env.repo.get(records[1].id, env.owner)
    assert queued.status == "queued"
    await env.history.retry(id, batch["id"], retry_key)
    assert (await env.repo.get(queued.id, env.owner)).generation == queued.generation
    env.fail.clear()
    await run(env, queued)
    assert (await env.history.snapshot(id, batch["id"]))["counts"] == {"completed": 2}
    # Reject a stale confirmation before accepting any jobs.
    with pytest.raises(AxisError, match="source_changed"):
        stale = request(axis, [doc]).model_copy(
            update={
                "documents": [
                    request(axis, [doc]).documents[0].model_copy(update={"source_hash": "f" * 64})
                ]
            }
        )
        await env.history.start(id, stale, uuid4())


@pytest.mark.parametrize("new_version", [False, True])
async def test_late_old_persistence_cannot_replace_newer_results(history, new_version):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    first = await env.history.start(id, request(axis, [env.original]), uuid4())
    old = (await jobs(env, first))[0]
    factory = env.history_worker.extractor_factory

    def fail_persistence(runtime, spec, *, extracting):
        extractor = factory(runtime, spec, extracting=extracting)
        if not extracting:

            async def fail(_):
                raise WorkflowFailure("synthetic_persistence_failure", retryable=True)

            extractor.persist = fail
        return extractor

    env.history_worker.extractor_factory = fail_persistence
    assert (await run(env, old)).status == "failed"
    env.history_worker.extractor_factory = factory
    next_axis = await approve(env, previous=axis) if new_version else axis
    newer = await env.history.start(id, request(next_axis, [env.original]), uuid4())
    assert (await run(env, (await jobs(env, newer))[0])).status == "completed"
    await env.history.retry(id, first["id"], uuid4())
    assert (await run(env, await env.repo.get(old.id, env.owner))).status == "completed"
    assert (await env.history.snapshot(id, first["id"]))["counts"] == {"superseded": 1}
    coverage = await env.history.coverage(id)
    assert coverage[str(env.original.id)]["version_id"] == next_axis["current_version_id"]
    assert sum(env.calls.values()) == 2


async def test_history_http_authorization_validation_and_recovery(history, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from sqlalchemy import update

    from src.adapters.storage.postgres.accounts import User
    from src.bootstrap.auth import get_authenticated_user
    from src.bootstrap.database import get_async_session
    from src.bootstrap.workspaces import get_workspace_runtime
    from src.core.auth.identity import AuthenticatedUser
    from src.extractors.personal_axes.routes import router

    env = history
    axis = await approve(env)
    body = request(axis, [env.original]).model_dump(mode="json")
    app = FastAPI()
    app.include_router(router)

    async def sql():
        async with env.repo.sessions() as session:
            yield session

    async def runtime():
        yield env.runtime

    app.dependency_overrides[get_async_session] = sql
    app.dependency_overrides[get_workspace_runtime] = runtime
    app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        id=env.owner, email="test@example.test"
    )
    monkeypatch.setattr("src.processing.runtime.get_repository", lambda: env.repo)

    @app.exception_handler(AxisError)
    async def error(_, cause):
        return JSONResponse({"detail": cause.code}, status_code=cause.status)

    path = f"/personal-axes/{axis['id']}/history"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://app.test"
    ) as client:
        assert (await client.get(path + "/notes")).json()["remaining"] == 1
        assert (await client.post(path + "/batches", json=body)).status_code == 422
        key = {"Idempotency-Key": str(uuid4())}
        assert (
            await client.post(
                path + "/batches", json={**body, "documents": body["documents"] * 2}, headers=key
            )
        ).status_code == 422
        assert (
            await client.post(path + "/batches", json={**body, "enabled": True}, headers=key)
        ).status_code == 422
        assert (
            await client.post(
                path + "/batches", json=body, headers={**key, "Origin": "https://evil.test"}
            )
        ).status_code == 403
        assert (await client.get(f"/personal-axes/{uuid4()}/history/notes")).status_code == 404
        foreign = {**body, "documents": [{"document_id": str(uuid4()), "source_hash": "f" * 64}]}
        assert (await client.post(path + "/batches", json=foreign, headers=key)).status_code == 409
        accepted = await client.post(path + "/batches", json=body, headers=key)
        assert accepted.status_code == 202
        batch = accepted.json()
        assert (await client.post(path + "/batches", json=body, headers=key)).json()["id"] == batch[
            "id"
        ]
        assert len((await client.get(path + "/batches")).json()["items"]) == 1
        assert (await client.get(path + f"/batches/{batch['id']}")).status_code == 200
        duplicate = (
            await client.post(
                path + "/batches", json=body, headers={"Idempotency-Key": str(uuid4())}
            )
        ).json()
        assert duplicate["counts"] == {"skipped": 1}
        assert (
            await client.get(f"/personal-axes/{uuid4()}/history/batches/{batch['id']}")
        ).status_code == 404
        assert (await client.post(path + f"/batches/{batch['id']}/stop", json={})).json()[
            "counts"
        ] == {"stopped": 1}
        async with env.repo.sessions.begin() as session:
            await session.execute(
                update(User).where(User.id == env.owner).values(laboratory_enabled=False)
            )
        assert (await client.get(path + "/notes")).status_code == 404
        assert (await client.post(path + "/batches", json=body, headers=key)).status_code == 404


async def test_changed_deleted_sources_and_date_filters_are_explicit(history):
    from datetime import UTC, datetime

    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    changed = await source(env, "Cambiar")
    deleted = await source(env, "Eliminar")
    batch = await env.history.start(id, request(axis, [changed, deleted]), uuid4())
    path = env.runtime.document_store._directory / f"{changed.id}.json"
    path.write_text(
        changed.model_copy(update={"content": changed.content + " Otra idea."}).model_dump_json()
    )
    await env.runtime.document_store.delete(deleted.id)
    for job in await jobs(env, batch):
        await run(env, job)
    final = await env.history.snapshot(id, batch["id"])
    assert final["counts"] == {"changed": 1, "deleted": 1}
    assert final["retryable"] == 0
    assert sum(env.calls.values()) == 0
    dated = build_document(
        NewDocument(content=env.original.content, authored_at=datetime(2025, 1, 2, 1, tzinfo=UTC))
    ).model_copy(update={"title": "Una nota del año pasado"})
    await env.runtime.document_store.save(dated)
    from datetime import date

    result = await env.history.notes(
        id, q="AÑO", date_from=date(2025, 1, 1), date_to=date(2025, 1, 1)
    )
    assert result["total"] == 1 and result["items"][0]["document_id"] == dated.id


async def test_regular_axis_jobs_are_not_duplicated_by_a_historical_batch(history):
    from test_emotion_processing import upload
    from test_personal_axis_processing import finish

    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    document, parent = await upload(env)
    note = next(
        row for row in (await env.history.notes(id))["items"] if row["document_id"] == document.id
    )
    assert note["status"] == "in_progress"
    batch = await env.history.start(id, request(axis, [document]), uuid4())
    assert batch["counts"] == {"skipped": 1}
    assert not await jobs(env, batch)
    assert (await finish(env, parent))[0].status == "completed"
    assert (await env.history.coverage(id))[str(document.id)]["version_id"] == axis[
        "current_version_id"
    ]
    assert sum(env.calls.values()) == 1


async def test_transient_coverage_failure_remains_retryable_without_provider_call(
    history, monkeypatch
):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    batch = await env.history.start(id, request(axis, [env.original]), uuid4())
    job = (await jobs(env, batch))[0]
    original = AxisHistory.coverage

    async def unavailable(*args):
        raise AxisError("axis_graph_unavailable", 503)

    monkeypatch.setattr(AxisHistory, "coverage", unavailable)
    await ExecuteProcessing(env.repo, env.registry, max_attempts=1)(job.id, job.generation)
    failed = await env.history.snapshot(id, batch["id"])
    assert failed["retryable"] == 1
    assert sum(env.calls.values()) == 0
    monkeypatch.setattr(AxisHistory, "coverage", original)
    await env.history.retry(id, batch["id"], uuid4())
    assert (await run(env, await env.repo.get(job.id, env.owner))).status == "completed"


async def test_stop_after_retry_stops_queued_attempts_without_resurrecting_on_key_replay(history):
    env = history
    axis = await approve(env)
    id = UUID(axis["id"])
    batch = await env.history.start(id, request(axis, [env.original]), uuid4())
    job = (await jobs(env, batch))[0]
    env.fail.add(axis["version"]["specification"]["profile"]["id"])
    await ExecuteProcessing(env.repo, env.registry, max_attempts=1)(job.id, job.generation)
    key = uuid4()
    await env.history.retry(id, batch["id"], key)
    assert (await env.history.stop(id, batch["id"]))["counts"] == {"stopped": 1}
    replay = await env.history.retry(id, batch["id"], key)
    assert replay["status"] == "stopped"
    calls = sum(env.calls.values())
    assert (await run(env, await env.repo.get(job.id, env.owner))).status == "completed"
    assert sum(env.calls.values()) == calls


async def test_concurrent_writes_from_the_same_snapshot_keep_only_the_newer_run(
    history, monkeypatch
):
    from contextlib import asynccontextmanager

    from test_axis_previews import Provider

    from src.extractors.artifacts import LayerArtifacts
    from src.extractors.personal_axes.extractor import PersonalAxisExtractor
    from src.extractors.personal_axes.store import ArcadeDBAxisStore

    env = history
    axis = await approve(env)
    extractor = PersonalAxisExtractor(
        env.runtime.document_store,
        LayerArtifacts(env.runtime.context.filesystem_root / "layers"),
        axis["version"]["specification"],
        provider=Provider(),
        store=ArcadeDBAxisStore(env.client),
        axis_id=UUID(axis["id"]),
        version_id=UUID(axis["current_version_id"]),
    )
    seed = await extractor.extract(env.original)
    await extractor.persist(seed)
    first, second = await extractor.extract(env.original), await extractor.extract(env.original)
    other = PersonalAxisExtractor(
        extractor.documents,
        extractor.artifacts,
        extractor.specification,
        store=extractor.store,
        axis_id=extractor.axis_id,
        version_id=extractor.version_id,
    )
    extractor.write_order, other.write_order = "000000000001:100", "000000000001:200"
    original = env.client.transaction
    entered, count = asyncio.Event(), 0

    class Proxy:
        def __init__(self, tx):
            self.tx = tx

        def __getattr__(self, name):
            return getattr(self.tx, name)

        async def query(self, query, *args, **kwargs):
            nonlocal count
            result = await self.tx.query(query, *args, **kwargs)
            if query.startswith("SELECT write_order") and count < 2:
                count += 1
                if count == 2:
                    entered.set()
                await asyncio.wait_for(entered.wait(), 10)
            return result

    @asynccontextmanager
    async def transaction():
        async with original() as tx:
            yield Proxy(tx)

    monkeypatch.setattr(env.client, "transaction", transaction)
    results = await asyncio.gather(
        extractor.persist(first), other.persist(second), return_exceptions=True
    )
    for writer, output, result in zip((extractor, other), (first, second), results, strict=True):
        if isinstance(result, Exception):
            await writer.persist(output)
    records = (
        await env.client.query(
            "SELECT id, write_order FROM AxisExtraction WHERE axis_id=:axis_id",
            {"axis_id": axis["id"]},
        )
    )["result"]
    assert records == [{"id": str(second.run_id), "write_order": other.write_order}]
