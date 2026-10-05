"""Opt-in tests against a migrated, isolated PROCESSING_TEST_DATABASE_URL."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.processing.dispatcher import dispatch_once
from src.processing.execution import (
    ExecuteProcessing,
    ResourceBusy,
    WorkflowDefinition,
    WorkflowFailure,
    WorkflowRegistry,
)
from src.processing.models import (
    ProcessingEvent,
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.processing.repository import LeaseLost, ProcessingRepository
from src.user_management.models import User
from src.workspaces.models import UserWorkspace

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"),
        reason="requires isolated PostgreSQL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def store():
    engine = create_async_engine(os.environ["PROCESSING_TEST_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner = uuid4()
    async with sessions.begin() as session:
        session.add(User(id=owner, email=f"{owner}@test.local", hashed_password="unused"))
        await session.flush()
        session.add(
            UserWorkspace(
                user_id=owner,
                arcadedb_instance_key="test",
                database_name=f"test_{owner.hex}",
                graph_username=f"test_{owner.hex}",
                graph_secret_ciphertext="unused",
                status="active",
            )
        )
    repository = ProcessingRepository(sessions, lease_seconds=3)
    try:
        yield repository, owner
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ProcessingReceipt).where(ProcessingReceipt.user_id == owner)
            )
            ids = select(ProcessingRecord.id).where(ProcessingRecord.user_id == owner)
            await session.execute(
                delete(ProcessingOutbox).where(ProcessingOutbox.processing_id.in_(ids))
            )
            await session.execute(delete(ProcessingEvent).where(ProcessingEvent.user_id == owner))
            await session.execute(delete(ProcessingRecord).where(ProcessingRecord.user_id == owner))
            await session.execute(delete(UserWorkspace).where(UserWorkspace.user_id == owner))
            await session.execute(delete(User).where(User.id == owner))
        await engine.dispose()


async def job(store, resource_id=None):
    repository, owner = store
    return await repository.create(
        user_id=owner,
        workflow="test",
        stage="extract",
        resource_kind="document",
        resource_id=resource_id or uuid4(),
        config={"model": "test-model"},
    )


def executor(repository, run, transitions=()):
    registry = WorkflowRegistry()
    registry.register("test", 1, WorkflowDefinition(run, frozenset(transitions)))
    return ExecuteProcessing(repository, registry)


async def expire(repository, processing_id):
    async with repository.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == processing_id)
            .values(lease_expires_at=func.now())
        )


async def test_state_event_outbox_are_atomic_and_owner_scoped(store):
    repo, owner = store
    record = await job(store)
    assert await repo.get(record.id, uuid4()) is None
    async with repo.sessions() as session:
        event = await session.scalar(
            select(ProcessingEvent).where(ProcessingEvent.processing_id == record.id)
        )
        outbox = await session.scalar(
            select(ProcessingOutbox).where(ProcessingOutbox.processing_id == record.id)
        )
        assert (event.user_id, event.version, event.status) == (owner, 1, "queued")
        assert outbox.generation == record.generation
    with pytest.raises(ValueError, match="workspace_unavailable"):
        await repo.create(
            user_id=uuid4(),
            workflow="test",
            stage="extract",
            resource_kind="document",
            resource_id=uuid4(),
        )


async def test_duplicate_execution_only_runs_once(store):
    repo, owner = store
    record = await job(store)
    calls = 0
    started, release = asyncio.Event(), asyncio.Event()

    async def run(context):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        await context.advance("embed", artifact="durable.json")

    execute = executor(repo, run, [("extract", "embed")])
    first = asyncio.create_task(execute(record.id, 1))
    await started.wait()
    with pytest.raises(ResourceBusy):
        await execute(record.id, 1)
    release.set()
    await first
    await execute(record.id, 1)
    current = await repo.get(record.id, owner)
    assert calls == 1
    assert (current.status, current.stage, current.checkpoints) == (
        "completed",
        "embed",
        {"artifact": "durable.json"},
    )
    async with repo.sessions() as session:
        events = list(
            (
                await session.scalars(
                    select(ProcessingEvent)
                    .where(ProcessingEvent.processing_id == record.id)
                    .order_by(ProcessingEvent.version)
                )
            ).all()
        )
    assert [event.version for event in events] == [1, 2, 3, 4]


async def test_retry_resumes_checkpoint_and_old_messages_are_ignored(store):
    repo, owner = store
    record = await job(store)
    extracted = 0

    async def run(context):
        nonlocal extracted
        if context.record.stage == "extract":
            extracted += 1
            await context.advance("embed", extraction="persisted")
            raise WorkflowFailure("provider_rate_limit", retry_delay=0)
        assert context.record.checkpoints["extraction"] == "persisted"

    execute = executor(repo, run, [("extract", "embed")])
    await execute(record.id, 1)
    current = await repo.get(record.id, owner)
    assert (current.status, current.generation) == ("retrying", 2)
    await execute(record.id, 1)
    await execute(record.id, 2)
    assert (await repo.get(record.id, owner)).status == "completed"
    assert extracted == 1


async def test_retries_are_bounded_and_permanent_failure_is_not_retried(store):
    repo, owner = store
    record = await job(store)

    async def temporary(context):
        raise WorkflowFailure("provider_timeout", retry_delay=0)

    execute = executor(repo, temporary)
    for generation in range(1, 5):
        await execute(record.id, generation)
    current = await repo.get(record.id, owner)
    assert (current.status, current.attempts) == ("failed", 4)

    permanent = await job(store)

    async def invalid(context):
        await context.advance("not_allowed")

    await executor(repo, invalid)(permanent.id, 1)
    current = await repo.get(permanent.id, owner)
    assert (current.status, current.error_code) == ("failed", "invalid_workflow_transition")


async def test_expired_lease_fences_old_worker_and_recovers(store):
    repo, owner = store
    record = await job(store)
    old = await repo.acquire(record.id, 1, "old-worker")
    await expire(repo, record.id)
    assert await repo.recover() == 1
    with pytest.raises(LeaseLost):
        await repo.advance(old, "embed", {"bad": True})
    new = await repo.acquire(record.id, 2, "replacement")
    assert new.fencing_token > old.fencing_token
    await repo.finish(new)
    assert (await repo.get(record.id, owner)).checkpoints == {}


async def test_two_jobs_for_same_resource_are_serialized(store):
    repo, _ = store
    resource = uuid4()
    first, second = await job(store, resource), await job(store, resource)
    async with repo.resource_guard(first.id) as acquired:
        assert acquired
        async with repo.resource_guard(second.id) as locked:
            assert not locked
    async with repo.resource_guard(second.id) as locked:
        assert locked


async def test_outbox_failure_is_durable_and_dispatchers_do_not_double_claim(store):
    repo, _ = store
    record = await job(store)
    claims = await asyncio.gather(repo.claim_outbox(), repo.claim_outbox())
    rows = claims[0] + claims[1]
    assert len(rows) == 1 and rows[0].processing_id == record.id
    await repo.settle_outbox(rows[0], published=False)
    async with repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingOutbox)
            .where(ProcessingOutbox.id == rows[0].id)
            .values(available_at=func.now())
        )

    async def broker_down(*args):
        raise ConnectionError("unavailable")

    assert await dispatch_once(repo, broker_down) == 1
    async with repo.sessions() as session:
        outbox = await session.get(ProcessingOutbox, rows[0].id)
        assert outbox.published_at is None
        assert outbox.claim_token is None
        assert outbox.attempts == 2


async def test_published_but_lost_delivery_is_recreated(store):
    repo, owner = store
    record = await job(store)
    rows = await repo.claim_outbox()
    await repo.settle_outbox(rows[0], published=True)
    assert await repo.recover(replay_seconds=0) == 1
    current = await repo.get(record.id, owner)
    # Preserve the generation so a valid delivery already queued keeps its FIFO position.
    assert current.generation == 1
    assert (await repo.claim_outbox())[0].generation == 1


async def test_heartbeat_preserves_long_execution(store):
    repo, owner = store
    record = await job(store)

    async def slow(context):
        await asyncio.sleep(3.2)
        assert await repo.recover() == 0

    await executor(repo, slow)(record.id, 1)
    assert (await repo.get(record.id, owner)).status == "completed"


async def test_cancelled_worker_is_recoverable(store):
    repo, owner = store
    record = await job(store)
    started = asyncio.Event()

    async def interrupted(context):
        await context.advance("embed", extraction="safe")
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(executor(repo, interrupted, [("extract", "embed")])(record.id, 1))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await expire(repo, record.id)
    await repo.recover()
    current = await repo.get(record.id, owner)
    assert (current.status, current.stage, current.checkpoints) == (
        "retrying",
        "embed",
        {"extraction": "safe"},
    )


@pytest.mark.skipif(not os.getenv("PROCESSING_TEST_RABBITMQ_URL"), reason="requires RabbitMQ")
async def test_real_taskiq_workers_scale_and_ack_after_durable_completion(store, tmp_path):
    import signal
    import subprocess
    import sys
    from pathlib import Path

    from taskiq_aio_pika import AioPikaBroker

    repo, owner = store
    queue = f"processing.test.{uuid4().hex}"
    broker = AioPikaBroker(
        os.environ["PROCESSING_TEST_RABBITMQ_URL"],
        queue_name=queue,
        exchange_name=queue,
        declare_exchange_kwargs={"durable": True},
        declare_queues_kwargs={"durable": True},
    )
    task = broker.register_task(lambda *args: None, task_name="processing.execute")
    await broker.startup()
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["PROCESSING_TEST_DATABASE_URL"],
        "RABBITMQ_URL": os.environ["PROCESSING_TEST_RABBITMQ_URL"],
        "PROCESSING_QUEUE_NAME": queue,
        "PROCESSING_CONCURRENCY": "2",
        "PYTHONPATH": str(Path(__file__).parent.resolve()),
    }
    workers, logs = [], []
    try:
        for index in range(2):
            log = (tmp_path / f"worker-{index}.log").open("w")
            logs.append(log)
            workers.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "taskiq",
                        "worker",
                        "src.processing.broker:broker",
                        "src.processing.tasks",
                        "processing_worker_fixture",
                        "--workers",
                        "1",
                        "--max-async-tasks",
                        "2",
                        "--max-prefetch",
                        "0",
                        "--ack-type",
                        "manual",
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        records = [await job(store) for _ in range(12)]
        for record in records:
            await task.kiq(str(record.id), 1)
            await task.kiq(str(record.id), 1)  # Simulated confirm/commit crash duplicate.
        completed = []
        for _ in range(150):
            completed = [await repo.get(record.id, owner) for record in records]
            if all(record.status == "completed" for record in completed):
                break
            if any(worker.poll() is not None for worker in workers):
                break
            await asyncio.sleep(0.1)
        for log in logs:
            log.flush()
        evidence = "\n".join(path.read_text() for path in tmp_path.glob("*.log"))
        assert all(record.status == "completed" for record in completed), evidence
        assert all(record.attempts == 1 for record in completed)
        assert len({record.checkpoints["worker_pid"] for record in completed}) == 2

        interrupted = await repo.create(
            user_id=owner,
            workflow="test",
            stage="extract",
            resource_kind="document",
            resource_id=uuid4(),
            config={"delay": 30},
        )
        await task.kiq(str(interrupted.id), 1)
        for _ in range(100):
            current = await repo.get(interrupted.id, owner)
            if current.stage == "embed":
                break
            await asyncio.sleep(0.1)
        assert current.stage == "embed", "worker did not persist its checkpoint"
        os.kill(current.checkpoints["worker_pid"], signal.SIGKILL)
        await expire(repo, interrupted.id)
        assert await repo.recover() == 1
        await task.kiq(str(interrupted.id), 2)
        for _ in range(100):
            current = await repo.get(interrupted.id, owner)
            if current.status == "completed":
                break
            await asyncio.sleep(0.1)
        assert (current.status, current.attempts, current.checkpoints["artifact"]) == (
            "completed",
            2,
            "persisted",
        )
    finally:
        for worker in workers:
            if worker.poll() is None:
                os.killpg(worker.pid, signal.SIGTERM)
        for worker in workers:
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.wait(timeout=5)
        for log in logs:
            log.close()
        for name in (queue, f"{queue}.dead_letter", f"{queue}.delay"):
            await broker.write_channel.queue_delete(name)
        await broker.write_channel.exchange_delete(queue)
        await broker.shutdown()


async def test_failed_retry_transaction_keeps_state_and_event_history(store):
    repo, owner = store
    record = await job(store)
    leased = await repo.acquire(record.id, 1, "worker")
    with pytest.raises(ValueError, match="invalid_retry_delay"):
        await repo.finish(leased, status="retrying", retry_delay=-1)
    current = await repo.get(record.id, owner)
    assert (current.status, current.version, current.generation) == ("running", 2, 1)
    async with repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingEvent)
                .where(ProcessingEvent.processing_id == record.id)
            )
            == 2
        )


async def test_broker_outage_keeps_existing_outbox_instead_of_creating_duplicates(store):
    repo, owner = store
    record = await job(store)
    assert await repo.recover(replay_seconds=0) == 0
    assert (await repo.get(record.id, owner)).generation == 1
    assert len(await repo.claim_outbox()) == 1


async def test_suspended_workspace_is_not_processed(store):
    repo, owner = store
    record = await job(store)
    async with repo.sessions.begin() as session:
        await session.execute(
            update(UserWorkspace).where(UserWorkspace.user_id == owner).values(status="suspended")
        )

    async def forbidden(context):
        pytest.fail("suspended workspace executed")

    await executor(repo, forbidden)(record.id, 1)
    current = await repo.get(record.id, owner)
    assert (current.status, current.error_code) == ("failed", "workspace_unavailable")


async def test_expired_worker_keeps_resource_exclusive_until_it_stops(store):
    repo, owner = store
    record = await job(store)
    started, release = asyncio.Event(), asyncio.Event()
    effects = []

    async def old_worker(context):
        started.set()
        await release.wait()
        await context.assert_lease()
        effects.append("stale write")

    old_task = asyncio.create_task(executor(repo, old_worker)(record.id, 1))
    await started.wait()
    await expire(repo, record.id)
    assert await repo.recover() == 1

    async def replacement(context):
        await context.assert_lease()
        effects.append("current write")

    execute = executor(repo, replacement)
    with pytest.raises(ResourceBusy):
        await execute(record.id, 2)
    release.set()
    await old_task
    await execute(record.id, 2)
    assert effects == ["current write"]
    assert (await repo.get(record.id, owner)).status == "completed"
