"""Real PostgreSQL locks, routes, sessions, outbox and worker; Resend HTTP is simulated."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.providers.email.resend import ResendMailTransport
from src.adapters.storage.postgres.accounts import AccessToken, OAuthAccount, User
from src.adapters.storage.postgres.recovery_models import (
    RecoveryAddress,
    RecoveryDelivery,
    RecoveryIP,
)
from src.adapters.storage.postgres.recovery_repository import RecoveryError, RecoveryRepository
from src.bootstrap.auth import (
    InvitationDatabaseStrategy,
    UserManager,
    build_router,
    get_database_strategy,
    session,
)
from src.bootstrap.database import get_access_token_db, get_async_session
from src.bootstrap.recovery import (
    RecoverPassword,
    RecoverySecrets,
    SendRecoveryEmail,
    get_password_recovery,
)
from src.config import Settings
from src.exteriorization.models import InvitationPreference, PushSubscription
from src.processing.execution import ExecuteProcessing, WorkflowRegistry
from src.processing.models import ProcessingEvent, ProcessingOutbox, ProcessingRecord
from src.processing.repository import ProcessingRepository

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("RECOVERY_TEST_DATABASE_URL"), reason="requires isolated migrated PostgreSQL"
    ),
]
PASSWORD = "a-long-initial-private-password"
NEW_PASSWORD = "a-different-long-private-password"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def env(monkeypatch):
    engine = create_async_engine(os.environ["RECOVERY_TEST_DATABASE_URL"], hide_parameters=True)
    if not engine.url.database.startswith("recovery_test"):
        raise RuntimeError("Recovery integration tests require a disposable recovery_test database")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        auth_session_secret="auth-test-secret",
        resend_api_key="fake-resend-key",
        auth_email_from="El Espejo <access@example.com>",
        password_recovery_secret="a-separate-long-recovery-test-secret",
    )
    repository = RecoveryRepository(sessions)
    crypto = RecoverySecrets(settings.password_recovery_secret)
    value = SimpleNamespace(
        sessions=sessions,
        repository=repository,
        crypto=crypto,
        now=datetime.now(UTC),
        mails=[],
        provider_status=200,
    )

    async def now(_session):
        return value.now

    repository.now = now
    value.recovery = RecoverPassword(repository, crypto)
    ids = [uuid4() for _ in range(3)]
    value.owner, value.google, value.linked = ids
    value.email = f"local-{ids[0]}@example.com"
    value.google_email = f"google-{ids[1]}@example.com"
    value.linked_email = f"linked-{ids[2]}@example.com"
    async with sessions.begin() as sql:
        for user_id, email, local in zip(
            ids, [value.email, value.google_email, value.linked_email], [True, False, True]
        ):
            sql.add(
                User(
                    id=user_id,
                    email=email,
                    password_login_enabled=local,
                    hashed_password=PasswordHelper().hash(PASSWORD),
                )
            )
        await sql.flush()
        for owner, email in [
            (value.google, value.google_email),
            (value.linked, value.linked_email),
        ]:
            sql.add(
                OAuthAccount(
                    user_id=owner,
                    oauth_name="google",
                    access_token="unused",
                    account_id=str(owner),
                    account_email=email,
                )
            )

    async def resend(request):
        import json

        body = json.loads(request.content)
        value.mails.append({"body": body, "key": request.headers["Idempotency-Key"]})
        return httpx.Response(value.provider_status, json={"id": str(uuid4())})

    mail = ResendMailTransport(
        settings.resend_api_key, settings.auth_email_from, transport=httpx.MockTransport(resend)
    )
    registry = WorkflowRegistry()
    registry.register(
        "password_recovery_email", 1, SendRecoveryEmail(repository, crypto, mail).definition
    )
    value.jobs = ProcessingRepository(sessions, lease_seconds=30)
    value.executor = ExecuteProcessing(value.jobs, registry)
    monkeypatch.setattr("src.bootstrap.auth.get_settings", lambda: settings)
    monkeypatch.setattr("src.bootstrap.recovery.get_settings", lambda: settings)
    app = FastAPI()
    router = build_router(settings)
    router.add_api_route("/session", session, methods=["GET"])
    app.include_router(router)

    async def db():
        async with sessions() as sql:
            yield sql

    async def strategy(access_tokens=Depends(get_access_token_db)):
        return InvitationDatabaseStrategy(access_tokens, lifetime_seconds=3600)

    app.dependency_overrides[get_async_session] = db
    app.dependency_overrides[get_password_recovery] = lambda: value.recovery
    app.dependency_overrides[get_database_strategy] = strategy
    value.transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=value.transport, base_url="https://recovery.test"
    ) as client:
        value.client = client
        try:
            yield value
        finally:
            async with sessions.begin() as sql:
                await sql.execute(delete(RecoveryDelivery))
                await sql.execute(delete(RecoveryAddress))
                await sql.execute(delete(RecoveryIP))
                await sql.execute(delete(ProcessingOutbox))
                await sql.execute(delete(ProcessingEvent))
                await sql.execute(delete(ProcessingRecord))
                await sql.execute(delete(PushSubscription))
                await sql.execute(delete(InvitationPreference))
                await sql.execute(delete(AccessToken))
                await sql.execute(delete(OAuthAccount))
                await sql.execute(delete(User))
            await engine.dispose()


async def request(env, email=None):
    return await env.client.post("/auth/forgot-password", json={"email": email or env.email})


async def reset(env, code, password=NEW_PASSWORD, email=None):
    return await env.client.post(
        "/auth/reset-password",
        json={"email": email or env.email, "code": code, "password": password},
    )


async def code_for(env, email=None):
    async with env.sessions() as sql:
        address = await sql.get(RecoveryAddress, env.crypto.email_key(email or env.email))
        return env.crypto.cipher.decrypt(address.code_ciphertext.encode()).decode()


async def jobs(env):
    async with env.sessions() as sql:
        return list(
            (
                await sql.scalars(select(ProcessingRecord).order_by(ProcessingRecord.created_at))
            ).all()
        )


async def login(env, password=PASSWORD):
    return await env.client.post("/auth/login", data={"username": env.email, "password": password})


async def rejected(action, code):
    with pytest.raises(RecoveryError) as failure:
        await action
    assert failure.value.code == code


async def test_generic_response_only_local_and_linked_receive_mail(env):
    missing = f"missing-{uuid4()}@example.com"
    responses = [
        await request(env, email)
        for email in [env.email, missing, env.google_email, env.linked_email]
    ]
    assert all(response.status_code == 202 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    records = await jobs(env)
    assert {record.user_id for record in records} == {env.owner, env.linked}
    for record in records:
        await env.executor(record.id, record.generation)
    assert len(env.mails) == 2
    assert {mail["body"]["to"][0] for mail in env.mails} == {env.email, env.linked_email}
    assert all("https://" not in mail["body"]["text"] for mail in env.mails)
    async with env.sessions() as sql:
        assert await sql.scalar(select(func.count()).select_from(ProcessingEvent)) == 0
    assert env.google_email not in str(responses[2].json())


async def test_single_use_password_change_revokes_only_owners_sessions_and_push(
    env,
):
    assert (await login(env)).status_code == 204
    assert (await env.client.get("/auth/session")).status_code == 200
    async with env.sessions.begin() as sql:
        sql.add(AccessToken(token="other-user-session", user_id=env.linked, session_version=0))
        for owner in [env.owner, env.linked]:
            sql.add(
                PushSubscription(
                    user_id=owner,
                    endpoint=f"https://fcm.googleapis.com/{owner}",
                    p256dh="test",
                    auth="test",
                    session_fingerprint="test",
                    active=True,
                )
            )
    await request(env)
    code = await code_for(env)
    assert code.isdecimal() and len(code) == 6
    assert (await reset(env, code)).status_code == 204
    assert (await env.client.get("/auth/session")).status_code == 401
    assert (await login(env)).status_code == 400
    assert (await login(env, NEW_PASSWORD)).status_code == 204
    assert (await reset(env, code)).json()["detail"] == "recovery_invalid_code"
    async with env.sessions() as sql:
        user = await sql.get(User, env.owner)
        assert user.session_version == 1
        assert PasswordHelper().verify_and_update(NEW_PASSWORD, user.hashed_password)[0]
        assert await sql.get(AccessToken, "other-user-session") is not None
        subscriptions = list((await sql.scalars(select(PushSubscription))).all())
        assert {row.user_id: row.active for row in subscriptions} == {
            env.owner: False,
            env.linked: True,
        }
        address = await sql.get(RecoveryAddress, env.crypto.email_key(env.email))
        assert address.code_mac is None and address.code_ciphertext is None


async def test_resend_preserves_code_expiry_and_wrong_attempt_count(env):
    await request(env)
    code = await code_for(env)
    async with env.sessions() as sql:
        expiry = (await sql.get(RecoveryAddress, env.crypto.email_key(env.email))).expires_at
    wrong = "000000" if code != "000000" else "111111"
    assert (await reset(env, wrong)).status_code == 400
    env.now += timedelta(seconds=60)
    await request(env)
    assert await code_for(env) == code
    async with env.sessions() as sql:
        row = await sql.get(RecoveryAddress, env.crypto.email_key(env.email))
        assert row.expires_at == expiry and row.failed_attempts == 1
    assert len(await jobs(env)) == 2
    assert (await reset(env, code)).status_code == 204


async def test_email_cooldown_hour_and_daily_budgets_survive_new_use_case_instances(env):
    for offset in [0, 59, 60, 120, 180]:
        env.now = datetime.now(UTC) + timedelta(seconds=offset)
        # Distinct IPs cannot bypass the per-address limit, even across processes.
        service = RecoverPassword(RecoveryRepository(env.sessions), env.crypto)
        service.repository.now = env.repository.now
        await service.request(env.email, f"192.0.2.{offset + 1}")
    assert len(await jobs(env)) == 3
    for hour in [2, 4, 6]:
        for minute in [0, 2, 4]:
            env.now = datetime.now(UTC) + timedelta(hours=hour, minutes=minute)
            await env.recovery.request(env.email, f"198.51.100.{hour + minute}")
    assert len(await jobs(env)) == 10
    env.now += timedelta(hours=2)
    await env.recovery.request(env.email, "203.0.113.1")
    assert len(await jobs(env)) == 10
    env.now += timedelta(days=1)
    await env.recovery.request(env.email, "203.0.113.2")
    assert len(await jobs(env)) == 11


async def test_ip_quota_is_shared_by_request_and_reset_and_uses_retry_after(env):
    for _ in range(5):
        assert (await request(env, f"missing-{uuid4()}@example.com")).status_code == 202
        assert (await reset(env, "123456")).status_code == 400
    blocked = await request(env)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    env.now += timedelta(minutes=10, seconds=1)
    assert (await request(env)).status_code == 202


async def test_five_failures_persist_and_no_resend_can_reset_attempts(env):
    await env.recovery.request(env.email, "192.0.2.1")
    code = await code_for(env)
    wrong = "000000" if code != "000000" else "111111"
    for index in range(5):
        await rejected(
            env.recovery.reset(env.email, wrong, NEW_PASSWORD, f"192.0.2.{index + 2}"),
            "recovery_invalid_code",
        )
    await rejected(
        env.recovery.reset(env.email, code, NEW_PASSWORD, "192.0.2.8"), "recovery_invalid_code"
    )
    env.now += timedelta(seconds=61)
    await env.recovery.request(env.email, "192.0.2.9")
    assert len(await jobs(env)) == 1
    async with env.sessions() as sql:
        row = await sql.get(RecoveryAddress, env.crypto.email_key(env.email))
        assert row.failed_attempts == 5 and row.code_ciphertext is None
    env.now += timedelta(minutes=10)
    await env.recovery.request(env.email, "192.0.2.10")
    assert len(await jobs(env)) == 2


async def test_expiry_invalid_password_and_wrong_email_do_not_change_password(env):
    await request(env)
    code = await code_for(env)
    assert (await reset(env, code, email=env.linked_email)).status_code == 400
    assert (await reset(env, code, password="short")).json()[
        "detail"
    ] == "recovery_invalid_password"
    env.now += timedelta(minutes=10)
    assert (await reset(env, code)).json()["detail"] == "recovery_invalid_code"
    assert (await login(env)).status_code == 204
    await env.repository.cleanup()
    async with env.sessions() as sql:
        row = await sql.get(RecoveryAddress, env.crypto.email_key(env.email))
        assert row.code_ciphertext is None


async def test_parallel_requests_and_resets_are_atomic(env):
    await asyncio.gather(*(env.recovery.request(env.email, f"192.0.2.{i}") for i in range(1, 21)))
    assert len(await jobs(env)) == 1
    code = await code_for(env)
    outcomes = await asyncio.gather(
        *(
            env.recovery.reset(env.email, code, NEW_PASSWORD, f"198.51.100.{i}")
            for i in range(1, 11)
        ),
        return_exceptions=True,
    )
    assert sum(outcome is None for outcome in outcomes) == 1
    assert all(outcome is None or isinstance(outcome, RecoveryError) for outcome in outcomes)
    async with env.sessions() as sql:
        assert (await sql.get(User, env.owner)).session_version == 1


async def test_worker_replay_transient_retries_expiry_and_consumption(env):
    await request(env)
    record = (await jobs(env))[0]
    env.provider_status = 503
    await env.executor(record.id, 1)
    async with env.sessions.begin() as sql:
        row = await sql.get(ProcessingRecord, record.id)
        assert row.status == "retrying" and row.generation == 2
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    env.provider_status = 200
    await env.executor(record.id, 2)
    await env.executor(record.id, 2)
    assert len(env.mails) == 2 and env.mails[0] == {
        **env.mails[1]
    }  # Same protected code and idempotency key.
    async with env.sessions() as sql:
        assert (await sql.get(ProcessingRecord, record.id)).status == "completed"
    env.now += timedelta(seconds=61)
    await request(env)
    pending = (await jobs(env))[-1]
    await reset(env, await code_for(env))
    await env.executor(pending.id, 1)
    assert len(env.mails) == 2


async def test_late_login_token_with_pre_reset_version_is_rejected(env):
    async with env.sessions() as sql:
        stale_user = await sql.get(User, env.owner)
    await request(env)
    assert (await reset(env, await code_for(env))).status_code == 204
    async with env.sessions() as sql:
        from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase

        strategy = InvitationDatabaseStrategy(
            SQLAlchemyAccessTokenDatabase(sql, AccessToken), lifetime_seconds=3600
        )
        token = await strategy.write_token(stale_user)
    async with env.sessions() as sql:
        strategy = InvitationDatabaseStrategy(
            SQLAlchemyAccessTokenDatabase(sql, AccessToken), lifetime_seconds=3600
        )
        manager = UserManager(SQLAlchemyUserDatabase(sql, User, OAuthAccount), "test-secret")
        assert await strategy.read_token(token, manager) is None


async def test_successful_password_login_confirms_local_credentials(env):
    async with env.sessions.begin() as sql:
        row = await sql.get(User, env.owner)
        row.password_login_enabled = False
    await request(env)
    assert not await jobs(env)
    assert (await login(env)).status_code == 204
    env.now += timedelta(seconds=61)
    await request(env)
    assert len(await jobs(env)) == 1


async def test_concurrent_ip_requests_cannot_exceed_ten(env):
    outcomes = await asyncio.gather(
        *(env.recovery.request(f"missing-{uuid4()}@example.com", "192.0.2.42") for _ in range(20)),
        return_exceptions=True,
    )
    assert sum(outcome is None for outcome in outcomes) == 10
    assert (
        sum(
            isinstance(outcome, RecoveryError) and outcome.code == "recovery_rate_limited"
            for outcome in outcomes
        )
        == 10
    )


async def test_concurrent_wrong_codes_never_exceed_five_attempts(env):
    await env.recovery.request(env.email, "192.0.2.1")
    code = await code_for(env)
    wrong = "111111" if code != "111111" else "222222"
    await asyncio.gather(
        *(env.recovery.reset(env.email, wrong, NEW_PASSWORD, f"192.0.2.{i}") for i in range(2, 22)),
        return_exceptions=True,
    )
    async with env.sessions() as sql:
        address = await sql.get(RecoveryAddress, env.crypto.email_key(env.email))
        assert address.failed_attempts == 5 and address.code_ciphertext is None


async def test_outbox_dispatch_and_late_worker_expiry(env):
    from src.processing.dispatcher import dispatch_once

    await request(env)
    assert (
        await dispatch_once(
            env.jobs,
            lambda identifier, generation: env.executor(UUID(identifier), generation),
        )
        == 1
    )
    assert len(env.mails) == 1
    async with env.sessions() as sql:
        assert (await sql.scalar(select(ProcessingOutbox))).published_at is not None
    env.now += timedelta(seconds=61)
    await request(env)
    record = (await jobs(env))[-1]
    async with env.sessions.begin() as sql:
        row = await sql.get(ProcessingRecord, record.id)
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    env.now += timedelta(minutes=10)
    await env.executor(record.id, record.generation)
    async with env.sessions() as sql:
        delivery = await sql.scalar(
            select(RecoveryDelivery).where(RecoveryDelivery.processing_id == record.id)
        )
        assert delivery.status == "expired"
    assert len(env.mails) == 1


async def test_inflight_password_hash_upgrade_cannot_restore_old_password(env):
    await request(env)
    code = await code_for(env)
    started, release = asyncio.Event(), asyncio.Event()
    upgraded_old_hash = PasswordHelper().hash(PASSWORD)

    async def login_with_upgrade():
        async with env.sessions() as sql:
            database = SQLAlchemyUserDatabase(sql, User, OAuthAccount)
            original_update = database.update

            async def paused_update(user, changes):
                started.set()
                await release.wait()
                return await original_update(user, changes)

            database.update = paused_update
            manager = UserManager(database, "test-secret")
            manager.password_helper.verify_and_update = lambda password, hashed: (
                True,
                upgraded_old_hash,
            )
            return await manager.authenticate(
                SimpleNamespace(username=env.email, password=PASSWORD)
            )

    login_task = asyncio.create_task(login_with_upgrade())
    await started.wait()
    reset_task = asyncio.create_task(
        env.recovery.reset(env.email, code, NEW_PASSWORD, "192.0.2.45")
    )
    await asyncio.wait({reset_task}, timeout=0.1)
    release.set()
    await asyncio.gather(login_task, reset_task)
    async with env.sessions() as sql:
        user = await sql.get(User, env.owner)
        assert PasswordHelper().verify_and_update(NEW_PASSWORD, user.hashed_password)[0]
        assert not PasswordHelper().verify_and_update(PASSWORD, user.hashed_password)[0]


async def test_internal_email_jobs_cannot_be_listed_or_retried_as_documents(env):
    from src.services.document_store import DocumentNotFoundError
    from src.use_cases.request_processing import RequestProcessing

    await request(env)
    record = (await jobs(env))[0]
    assert await env.jobs.list_for_owner(env.owner) == []
    runtime = SimpleNamespace(context=SimpleNamespace(user_id=env.owner))
    with pytest.raises(DocumentNotFoundError):
        await RequestProcessing(env.jobs, runtime).retry(record.id, uuid4())
