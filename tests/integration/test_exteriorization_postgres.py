"""Opt-in PostgreSQL tests: atomic occurrences, ownership and durable device sends."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    InvitationResponse,
    PushSubscription,
)
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.adapters.storage.postgres.notification_models import Notification
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.bootstrap.auth import require_authenticated
from src.bootstrap.invitations import get_invitations
from src.bootstrap.notifications import build_notification_center as NotificationRepository
from src.core.exteriorization.models import InvitationError, PushResult
from src.domain.documents import NewDocument
from src.main import app
from src.processing.execution import ExecuteProcessing, WorkflowRegistry
from src.processing.models import (
    ProcessingEvent,
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.processing.repository import ProcessingRepository
from src.processing.submissions import SubmissionConflict, SubmissionRepository
from src.services.document_store import FileDocumentStore
from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations
from src.use_cases.exteriorization.send_invitation import SendInvitation
from src.use_cases.submit_processing import SubmitDocument, recover_submissions

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("INVITATIONS_TEST_DATABASE_URL"),
        reason="requires isolated PostgreSQL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def store():
    engine = create_async_engine(os.environ["INVITATIONS_TEST_DATABASE_URL"], hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owners = [uuid4(), uuid4()]
    async with sessions.begin() as session:
        for owner in owners:
            session.add(User(id=owner, email=f"{owner}@example.com", hashed_password="unused"))
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
    repository = InvitationRepository(sessions)
    try:
        yield repository, owners
    finally:
        app.dependency_overrides.clear()
        async with sessions.begin() as session:
            for model in (
                InvitationResponse,
                InvitationDelivery,
                Invitation,
                PushSubscription,
                InvitationPreference,
                ProcessingReceipt,
            ):
                await session.execute(delete(model).where(model.user_id.in_(owners)))
            ids = select(ProcessingRecord.id).where(ProcessingRecord.user_id.in_(owners))
            await session.execute(
                delete(ProcessingOutbox).where(ProcessingOutbox.processing_id.in_(ids))
            )
            await session.execute(
                delete(ProcessingEvent).where(ProcessingEvent.user_id.in_(owners))
            )
            await session.execute(
                delete(ProcessingRecord).where(ProcessingRecord.user_id.in_(owners))
            )
            await session.execute(delete(UserWorkspace).where(UserWorkspace.user_id.in_(owners)))
            await session.execute(delete(User).where(User.id.in_(owners)))
        await engine.dispose()


async def setup(store, devices=1):
    repo, owners = store
    service = ConfigureInvitations(repo)
    subscriptions = [
        await service.subscribe(
            owners[0],
            f"session-{index}",
            f"https://fcm.googleapis.com/{uuid4()}",
            "public",
            "auth",
        )
        for index in range(devices)
    ]
    await service.configure(owners[0], True, "20:30", "UTC")
    return repo, owners[0], service, subscriptions


async def due_now(repo, owner, now=None):
    now = now or datetime.now(UTC)
    async with repo.sessions.begin() as session:
        preference = await session.get(InvitationPreference, owner)
        preference.next_due_at = now - timedelta(seconds=1)
    return now


async def rows(repo, model, owner):
    async with repo.sessions() as session:
        return list((await session.scalars(select(model).where(model.user_id == owner))).all())


class Transport:
    def __init__(self, *results):
        self.results = list(results)
        self.payloads = []

    async def send(self, subscription, payload, ttl):
        self.payloads.append((subscription, payload, ttl))
        return self.results.pop(0) if self.results else PushResult(accepted=True)


def executor(repo, transport):
    processing = ProcessingRepository(repo.sessions)
    registry = WorkflowRegistry()
    registry.register("invitation_push", 1, SendInvitation(repo, transport).definition)
    return ExecuteProcessing(processing, registry)


async def run_jobs(repo, owner, transport):
    run = executor(repo, transport)
    for job in await rows(repo, ProcessingRecord, owner):
        await run(job.id, job.generation)


async def test_concurrent_occurrence_generates_one_question_for_all_devices(store):
    repo, owner, service, subscriptions = await setup(store, devices=2)
    now = await due_now(repo, owner)
    assert (
        sum(await asyncio.gather(*[ScheduleInvitations(repo).execute(now) for _ in range(8)])) == 1
    )
    invitations = await rows(repo, Invitation, owner)
    assert len(invitations) == 1
    deliveries = await rows(repo, InvitationDelivery, owner)
    assert len(deliveries) == 2 and {item.invitation_id for item in deliveries} == {
        invitations[0].id
    }
    async with repo.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingOutbox)) >= 2
    assert await rows(repo, ProcessingEvent, owner) == []
    assert await ProcessingRepository(repo.sessions).list_for_owner(owner) == []
    # A settings change cannot reopen the same reserved local date.
    await service.configure(owner, True, "21:00", "UTC")
    await due_now(repo, owner, now)
    assert await ScheduleInvitations(repo).execute(now) == 0
    assert len(await rows(repo, Invitation, owner)) == 1
    transport = Transport()
    await run_jobs(repo, owner, transport)
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 2
    assert {item[1]["question"] for item in transport.payloads} == {invitations[0].question}


async def test_scheduler_rolls_back_everything_if_job_creation_fails(store, monkeypatch):
    repo, owner, _, _ = await setup(store)
    now = await due_now(repo, owner)

    def fail(*args):
        raise RuntimeError("simulated_outbox_failure")

    monkeypatch.setattr(ProcessingRepository, "schedule", fail)
    with pytest.raises(RuntimeError):
        await ScheduleInvitations(repo).execute(now)
    assert await rows(repo, Invitation, owner) == []
    assert await rows(repo, InvitationDelivery, owner) == []
    assert await rows(repo, Notification, owner) == []
    assert await rows(repo, ProcessingRecord, owner) == []
    assert (await ConfigureInvitations(repo).preferences(owner)).next_due_at < now


async def test_test_request_is_idempotent_rate_limited_and_does_not_consume_rotation(store):
    repo, owner, service, subscriptions = await setup(store)
    await service.configure(owner, False, "20:30", "UTC")
    key = uuid4()
    invitation = await service.test(owner, "session-0", subscriptions[0].id, key)
    replay = await service.test(owner, "session-0", subscriptions[0].id, key)
    assert invitation.id == replay.id
    inbox = NotificationRepository(repo.sessions)
    page = await inbox.list(owner)
    assert len(page.items) == 1
    assert page.items[0].title == "Pregunta diaria de prueba"
    assert page.items[0].action.invitation_id == invitation.id
    assert page.items[0].body == invitation.question
    assert page.items[0].expires_at - page.items[0].published_at == timedelta(days=15)
    await inbox.mutate(owner, page.items[0].id, dismiss=True)
    await service.test(owner, "session-0", subscriptions[0].id, key)
    assert (await inbox.list(owner)).items == []
    with pytest.raises(InvitationError, match="test_rate_limited"):
        await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    transport = Transport()
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 1
    await service.configure(owner, True, "20:30", "UTC")
    now = await due_now(repo, owner)
    assert await ScheduleInvitations(repo).execute(now) == 1
    scheduled = [item for item in await rows(repo, Invitation, owner) if item.kind == "scheduled"]
    assert scheduled[0].candidate_id == "daily_01"


async def test_replay_of_test_created_before_inbox_restores_only_its_missing_notification(store):
    repo, owner, service, subscriptions = await setup(store)
    key = uuid4()
    invitation = await service.test(owner, "session-0", subscriptions[0].id, key)
    async with repo.sessions.begin() as session:
        await session.execute(delete(Notification).where(Notification.user_id == owner))
    await service.open_invitation(owner, invitation.id)
    replay = await service.test(owner, "session-0", subscriptions[0].id, key)
    assert replay.id == invitation.id
    page = await NotificationRepository(repo.sessions).list(owner)
    assert len(page.items) == 1
    assert page.items[0].action.invitation_id == invitation.id
    assert page.items[0].read_at is not None
    assert page.unread_count == 0
    assert len(await rows(repo, Invitation, owner)) == 1
    assert len(await rows(repo, InvitationDelivery, owner)) == 1


async def test_retry_keeps_question_and_skips_devices_already_accepted(store):
    repo, owner, _, _ = await setup(store, devices=2)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    transport = Transport(PushResult(retryable=True, code="push_transient_error"))
    await run_jobs(repo, owner, transport)
    deliveries = await rows(repo, InvitationDelivery, owner)
    assert sorted(item.status for item in deliveries) == ["accepted", "retrying"]
    async with repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(
                ProcessingRecord.user_id == owner,
                ProcessingRecord.status == "retrying",
            )
            .values(available_at=func.now())
        )
        await session.execute(
            update(InvitationDelivery)
            .where(
                InvitationDelivery.user_id == owner,
                InvitationDelivery.status == "retrying",
            )
            .values(next_attempt_at=func.now())
        )
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 3
    assert len({item[1]["invitation_id"] for item in transport.payloads}) == 1
    assert len({item[1]["question"] for item in transport.payloads}) == 1
    assert all(item.status == "accepted" for item in await rows(repo, InvitationDelivery, owner))


async def test_expired_endpoint_is_invalidated_without_disabling_other_devices(store):
    repo, owner, service, _ = await setup(store, devices=2)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    await run_jobs(
        repo, owner, Transport(PushResult(expired=True, code="push_subscription_expired"))
    )
    subscriptions = await rows(repo, PushSubscription, owner)
    assert sorted(item.active for item in subscriptions) == [False, True]
    assert (await service.preferences(owner)).enabled
    assert sorted(item.status for item in await rows(repo, InvitationDelivery, owner)) == [
        "accepted",
        "failed",
    ]


async def test_disabling_cancels_pending_and_retrying_deliveries(store):
    repo, owner, service, _ = await setup(store, devices=2)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    transport = Transport(
        PushResult(retryable=True, code="push_transient_error"),
        PushResult(retryable=True, code="push_transient_error"),
    )
    await run_jobs(repo, owner, transport)
    await service.configure(owner, False, "20:30", "UTC")
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 2
    assert all(item.status == "cancelled" for item in await rows(repo, InvitationDelivery, owner))
    assert (await service.preferences(owner)).next_due_at is None


async def test_logout_only_deactivates_current_session(store):
    repo, owner, _, subscriptions = await setup(store, devices=2)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    await ConfigureInvitations(repo).deactivate_session(owner, "session-0")
    states = {item.id: item.active for item in await rows(repo, PushSubscription, owner)}
    assert states == {subscriptions[0].id: False, subscriptions[1].id: True}
    transport = Transport()
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 1


async def test_expired_occurrence_and_delivery_are_never_sent(store):
    repo, owner, _, _ = await setup(store)
    now = datetime.now(UTC)
    await due_now(repo, owner, now - timedelta(hours=3))
    assert await ScheduleInvitations(repo).execute(now) == 0
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    async with repo.sessions.begin() as session:
        await session.execute(
            update(Invitation)
            .where(Invitation.user_id == owner)
            .values(expires_at=now - timedelta(seconds=1))
        )
    transport = Transport()
    await run_jobs(repo, owner, transport)
    assert transport.payloads == []
    assert (await rows(repo, InvitationDelivery, owner))[0].status == "expired"


async def test_no_subscriptions_generates_inbox_but_suspended_workspace_does_not(store):
    repo, owners = store
    async with repo.sessions.begin() as session:
        session.add(
            InvitationPreference(
                user_id=owners[0],
                enabled=True,
                local_time="20:30",
                timezone="UTC",
                next_due_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    assert await ScheduleInvitations(repo).execute() == 1
    repo, owner, _, _ = await setup(store)
    await due_now(repo, owner)
    async with repo.sessions.begin() as session:
        workspace = await session.get(UserWorkspace, owner)
        workspace.status = "suspended"
    assert await ScheduleInvitations(repo).execute() == 0


async def test_multiuser_isolation_and_first_open_are_idempotent(store):
    repo, owner, service, subscriptions = await setup(store)
    invitation = await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    stranger = store[1][1]
    for action in (
        service.get_invitation(stranger, invitation.id),
        service.open_invitation(stranger, invitation.id),
        service.unsubscribe(stranger, "session-0", subscriptions[0].id),
    ):
        with pytest.raises(InvitationError) as failure:
            await action
        assert failure.value.code in {"invitation_not_found", "subscription_not_found"}
    with pytest.raises(InvitationError, match="subscription_account_conflict"):
        await service.subscribe(stranger, "session-x", subscriptions[0].endpoint, "public", "auth")
    first, second = await asyncio.gather(
        service.open_invitation(owner, invitation.id),
        service.open_invitation(owner, invitation.id),
    )
    assert first.first_opened_at == second.first_opened_at
    assert await rows(repo, InvitationResponse, owner) == []


async def test_answer_link_recovers_after_original_write_and_preserves_content(
    store, tmp_path, monkeypatch
):
    repo, owner, service, subscriptions = await setup(store)
    invitation = await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    monkeypatch.setattr("src.bootstrap.invitations.get_invitation_repository", lambda: repo)
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner),
        document_store=FileDocumentStore(tmp_path),
        graph_store=SimpleNamespace(persist_document=AsyncMock()),
    )
    submissions = SubmissionRepository(ProcessingRepository(repo.sessions))
    original_accept = submissions.accept

    async def fail(*args):
        raise RuntimeError("simulated_commit_failure")

    monkeypatch.setattr(submissions, "accept", fail)
    key = uuid4()
    document = NewDocument(content="Escribo mi respuesta.")
    with pytest.raises(RuntimeError):
        await SubmitDocument(submissions, runtime).execute(
            document, key, invitation_id=invitation.id
        )
    assert len(await runtime.document_store.list()) == 1
    assert await rows(repo, InvitationResponse, owner) == []
    monkeypatch.setattr(submissions, "accept", original_accept)

    @asynccontextmanager
    async def runtime_factory(user_id):
        assert user_id == owner
        yield runtime

    await recover_submissions(submissions, runtime_factory)
    note, job = await SubmitDocument(submissions, runtime).execute(
        document,
        key,
        invitation_id=invitation.id,
    )
    assert note.content == "Escribo mi respuesta."
    assert note.metadata["invitation_id"] == str(invitation.id)
    links = await rows(repo, InvitationResponse, owner)
    assert len(links) == 1 and links[0].document_id == note.id
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await SubmitDocument(submissions, runtime).execute(document, key)
    with pytest.raises(InvitationError, match="invitation_not_found"):
        await SubmitDocument(
            submissions,
            SimpleNamespace(
                context=SimpleNamespace(user_id=store[1][1]),
                document_store=runtime.document_store,
            ),
        ).execute(document, uuid4(), invitation_id=invitation.id)
    await submissions.processing.mark_deleted(owner, note.id)
    assert await rows(repo, InvitationResponse, owner) == []


async def test_http_contract_ownership_and_csrf(store, monkeypatch):
    repo, owner, service, subscriptions = await setup(store)
    invitation = await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_invitations] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        response = await client.get(f"/exteriorization/invitations/{invitation.id}")
        assert response.status_code == 200 and response.json()["question"] == invitation.question
        assert "user_id" not in response.json()
        response = await client.put(
            "/exteriorization/preferences",
            headers={"Origin": "https://evil"},
            json={"enabled": False, "timezone": "UTC"},
        )
        assert response.status_code == 403
        app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=store[1][1])
        assert (
            await client.get(f"/exteriorization/invitations/{invitation.id}")
        ).status_code == 404


async def test_long_outage_recovers_today_without_replaying_yesterday(store):
    repo, owner, _, _ = await setup(store)
    now = datetime(2026, 10, 13, 21, tzinfo=UTC)
    await due_now(repo, owner, now - timedelta(days=2))
    assert await ScheduleInvitations(repo).execute(now) == 1
    invitation = (await rows(repo, Invitation, owner))[0]
    assert invitation.local_date.isoformat() == "2026-10-13"
    assert invitation.scheduled_at == datetime(2026, 10, 13, 20, 30, tzinfo=UTC)


async def test_recovery_after_accepted_send_does_not_repeat_external_effect(store):
    repo, owner, _, _ = await setup(store)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    processing = ProcessingRepository(repo.sessions)
    job = (await rows(repo, ProcessingRecord, owner))[0]
    leased = await processing.acquire(job.id, 1, "interrupted-worker")
    transport = Transport()
    sender = SendInvitation(repo, transport)
    from src.processing.execution import ExecutionContext

    await sender.execute(ExecutionContext(processing, leased, sender.definition))
    # Simulate process death after persisting acceptance, before runner completion.
    async with repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == job.id)
            .values(lease_expires_at=func.now())
        )
    assert await processing.recover() == 1
    current = await processing.get(job.id, owner)
    await executor(repo, transport)(current.id, current.generation)
    assert len(transport.payloads) == 1
    assert (await processing.get(job.id, owner)).status == "completed"


async def test_failed_runtime_job_is_reconciled_to_terminal_delivery(store):
    repo, owner, _, _ = await setup(store)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    async with repo.sessions.begin() as session:
        await session.execute(
            update(UserWorkspace).where(UserWorkspace.user_id == owner).values(status="suspended")
        )
    transport = Transport()
    await run_jobs(repo, owner, transport)
    assert transport.payloads == []
    await ScheduleInvitations(repo).execute()
    delivery = (await rows(repo, InvitationDelivery, owner))[0]
    assert (delivery.status, delivery.error_code) == ("failed", "push_job_failed")


async def test_retry_limit_is_per_device_and_durable(store):
    repo, owner, _, _ = await setup(store)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    transport = Transport(*[PushResult(retryable=True, code="push_transient_error")] * 4)
    for _ in range(4):
        await run_jobs(repo, owner, transport)
        async with repo.sessions.begin() as session:
            await session.execute(
                update(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == owner,
                    ProcessingRecord.status == "retrying",
                )
                .values(available_at=func.now())
            )
            await session.execute(
                update(InvitationDelivery)
                .where(
                    InvitationDelivery.user_id == owner,
                )
                .values(next_attempt_at=func.now())
            )
    await run_jobs(repo, owner, transport)
    delivery = (await rows(repo, InvitationDelivery, owner))[0]
    assert (len(transport.payloads), delivery.attempts, delivery.status) == (4, 4, "failed")


async def test_real_cookie_logout_deactivates_only_its_device(store, monkeypatch):
    from fastapi_users.db import SQLAlchemyUserDatabase

    from src.adapters.storage.postgres.accounts import AccessToken, OAuthAccount
    from src.bootstrap.auth import COOKIE_NAME, UserManager, get_user_manager
    from src.bootstrap.database import get_async_session
    from src.core.exteriorization.models import session_fingerprint

    repo, owner, service, subscriptions = await setup(store, devices=2)
    token = str(uuid4())
    await service.subscribe(
        owner, session_fingerprint(token), subscriptions[0].endpoint, "public", "auth"
    )
    async with repo.sessions.begin() as session:
        session.add(AccessToken(token=token, user_id=owner))

    async def session_dependency():
        async with repo.sessions() as session:
            yield session

    async def manager_dependency():
        async with repo.sessions() as session:
            yield UserManager(SQLAlchemyUserDatabase(session, User, OAuthAccount), "test-secret")

    app.dependency_overrides[get_async_session] = session_dependency
    app.dependency_overrides[get_user_manager] = manager_dependency
    monkeypatch.setattr("src.bootstrap.invitations.get_invitation_repository", lambda: repo)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="https://test",
            cookies={COOKIE_NAME: token},
        ) as client:
            assert (await client.get("/auth/session")).status_code == 200
            assert (await client.post("/auth/logout")).status_code == 204
            assert (await client.get("/auth/session")).status_code == 401
        states = {item.id: item.active for item in await rows(repo, PushSubscription, owner)}
        assert states == {subscriptions[0].id: False, subscriptions[1].id: True}
    finally:
        async with repo.sessions.begin() as session:
            await session.execute(delete(AccessToken).where(AccessToken.user_id == owner))


@pytest.mark.skipif(
    not os.getenv("INVITATIONS_TEST_RABBITMQ_URL"), reason="requires isolated RabbitMQ"
)
async def test_real_taskiq_workers_handle_duplicate_deliveries(store, tmp_path):
    import signal
    import subprocess
    import sys

    from taskiq_aio_pika import AioPikaBroker

    from src.processing.dispatcher import dispatch_once

    repo, owner, _, _ = await setup(store, devices=2)
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    queue = f"test.invitations.{uuid4().hex}"
    broker = AioPikaBroker(
        os.environ["INVITATIONS_TEST_RABBITMQ_URL"],
        queue_name=queue,
        exchange_name=queue,
        declare_exchange_kwargs={"durable": True},
        declare_queues_kwargs={"durable": True},
    )

    async def unused(processing_id: str, generation: int):
        pass

    task = broker.task(task_name="processing.execute")(unused)
    await broker.startup()
    workers, logs = [], []
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["INVITATIONS_TEST_DATABASE_URL"],
        "RABBITMQ_URL": os.environ["INVITATIONS_TEST_RABBITMQ_URL"],
        "PROCESSING_QUEUE_NAME": queue,
        "PROCESSING_CONCURRENCY": "1",
        "PYTHONPATH": os.pathsep.join(
            [
                os.environ.get("PYTHONPATH", ""),
                str(Path(__file__).parent.resolve()),
            ]
        ),
    }
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
                        "invitation_worker_fixture",
                        "--workers",
                        "1",
                        "--max-async-tasks",
                        "1",
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
        processing = ProcessingRepository(repo.sessions)
        assert await dispatch_once(processing, task.kiq) == 2
        jobs = await rows(repo, ProcessingRecord, owner)
        for job in jobs:
            await task.kiq(str(job.id), job.generation)
        for _ in range(150):
            deliveries = await rows(repo, InvitationDelivery, owner)
            records = await rows(repo, ProcessingRecord, owner)
            if all(item.status == "accepted" for item in deliveries) and all(
                item.status == "completed" for item in records
            ):
                break
            if any(worker.poll() is not None for worker in workers):
                break
            await asyncio.sleep(0.1)
        evidence = "\n".join(path.read_text() for path in tmp_path.glob("*.log"))
        assert all(item.status == "accepted" for item in deliveries), evidence
        assert all(item.status == "completed" for item in records), evidence
        assert all(item.attempts == 1 for item in deliveries)
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
        await broker.write_channel.queue_delete(queue)
        await broker.write_channel.exchange_delete(queue)
        await broker.shutdown()


async def test_http_document_upload_preserves_typed_invitation_contract(
    store, tmp_path, monkeypatch
):
    from src.bootstrap.workspaces import get_workspace_runtime

    repo, owner, service, subscriptions = await setup(store)
    invitation = await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner),
        document_store=FileDocumentStore(tmp_path),
        graph_store=SimpleNamespace(persist_document=AsyncMock()),
    )
    app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_workspace_runtime] = lambda: runtime
    monkeypatch.setattr("src.bootstrap.invitations.get_invitation_repository", lambda: repo)
    monkeypatch.setattr(
        "src.api.routes.processing.get_repository", lambda: ProcessingRepository(repo.sessions)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        key = str(uuid4())
        response = await client.post(
            "/v2/documents",
            headers={"Idempotency-Key": key},
            json={
                "content": "Solo mi texto.",
                "invitation_id": str(invitation.id),
            },
        )
        assert response.status_code == 202
        original = response.json()["document"]
        assert original["content"] == "Solo mi texto."
        assert original["metadata"]["invitation_id"] == str(invitation.id)
        assert len(await rows(repo, InvitationResponse, owner)) == 1
        response = await client.post(
            "/v2/documents",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "content": "Mi texto.",
                "invitation_id": str(uuid4()),
            },
        )
        assert response.status_code == 404
        assert len(await runtime.document_store.list()) == 1


async def test_push_binding_is_idempotent_and_changes_with_the_authenticated_session(store):
    repo, owner, service, subscriptions = await setup(store)
    original = subscriptions[0]
    repeated = await service.subscribe(owner, "session-0", original.endpoint, "public", "auth")
    assert repeated.binding_id == original.binding_id
    await ScheduleInvitations(repo).execute(await due_now(repo, owner))
    changed = await service.subscribe(owner, "new-session", original.endpoint, "public", "auth")
    assert changed.id == original.id and changed.binding_id != original.binding_id
    assert (await rows(repo, InvitationDelivery, owner))[0].status == "cancelled"
    invitation = await service.test(owner, "new-session", changed.id, uuid4())
    transport = Transport()
    await run_jobs(repo, owner, transport)
    assert len(transport.payloads) == 1
    assert transport.payloads[0][1]["binding_id"] == str(changed.binding_id)
    assert transport.payloads[0][1]["invitation_id"] == str(invitation.id)
