"""Read-only admin API and metadata reconciliation against isolated PostgreSQL."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.admin_main import app
from src.administration.activity import record_access
from src.administration.database import admin_session
from src.administration.models import DocumentMetric, InventoryState, MetricCoverage, UserActivity
from src.administration.repository import AdministrationRepository, period_start
from src.administration.sync import LOCK_ID, SyncInventory
from src.domain.documents import NewDocument, build_document
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.services.document_store import FileDocumentStore
from src.user_management.models import User
from src.workspaces.models import UserWorkspace

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("ADMIN_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def env(tmp_path):
    from sqlalchemy.engine import make_url

    assert make_url(os.environ["ADMIN_TEST_DATABASE_URL"]).database.startswith("admin_test")
    engine = create_async_engine(os.environ["ADMIN_TEST_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owners = [uuid4() for _ in range(3)]
    async with sessions.begin() as session:
        session.add_all(
            [
                User(
                    id=owner, email=email, is_active=index != 1, hashed_password="NEVER_EXPOSE_HASH"
                )
                for index, (owner, email) in enumerate(
                    zip(
                        owners,
                        ["alpha@example.com", "beta@example.com", "percent%literal@example.com"],
                        strict=True,
                    )
                )
            ]
        )
    async with sessions.begin() as session:
        session.add_all(
            [
                UserWorkspace(
                    user_id=owner,
                    arcadedb_instance_key="admin-test",
                    database_name=f"test_{owner.hex}",
                    graph_username=f"test_{owner.hex}",
                    graph_secret_ciphertext="NEVER_EXPOSE_WORKSPACE_SECRET",
                    status="active",
                )
                for owner in owners
            ]
        )
        await session.execute(update(User).where(User.id == owners[0]).values(created_at=None))
    root = tmp_path / "workspaces"
    root.mkdir()

    async def dependency():
        async with sessions.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            yield session

    app.dependency_overrides[admin_session] = dependency
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin.test"
        ) as client:
            yield sessions, owners, root, client
    finally:
        app.dependency_overrides.clear()
        async with sessions.begin() as session:
            await session.execute(
                delete(ProcessingReceipt).where(ProcessingReceipt.user_id.in_(owners))
            )
            # Remove extractor children before their parents.
            await session.execute(
                delete(ProcessingRecord).where(
                    ProcessingRecord.user_id.in_(owners),
                    ProcessingRecord.parent_processing_id.is_not(None),
                )
            )
            await session.execute(
                delete(ProcessingRecord).where(ProcessingRecord.user_id.in_(owners))
            )
            await session.execute(delete(UserWorkspace).where(UserWorkspace.user_id.in_(owners)))
            await session.execute(delete(User).where(User.id.in_(owners)))
            await session.execute(delete(MetricCoverage))
        await engine.dispose()


async def original(env, index=0, source="pwa_note", operation="upload_document", accepted=None):
    sessions, owners, root, _ = env
    document = build_document(NewDocument(content="PRIVATE_NOTE_CONTENT", source=source))
    await FileDocumentStore(root / str(owners[index]) / "documents").save(document)
    if operation:
        async with sessions.begin() as session:
            session.add(
                ProcessingReceipt(
                    user_id=owners[index],
                    operation=operation,
                    key=uuid4(),
                    request_hash="unused",
                    resource_kind="audio" if operation == "upload_audio" else "document",
                    resource_id=document.id,
                    config={},
                    manifest={},
                    accepted_at=accepted or datetime.now(UTC),
                    lease_expires_at=datetime.now(UTC),
                )
            )
    return document


async def test_api_is_separate_paginated_filtered_and_private(env):
    sessions, owners, root, client = env
    await original(env)
    await SyncInventory(sessions, root).run()
    response = await client.get("/api/admin/users", params={"per_page": 1, "is_active": "false"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["email"] == "beta@example.com"
    data = (await client.get("/api/admin/users")).json()
    assert data["total"] == 3
    assert data["items"][0]["notes_count"] == 1
    assert data["items"][0]["created_at"] is None
    assert set(data["items"][0]) == {
        "id",
        "email",
        "is_active",
        "created_at",
        "last_activity_at",
        "notes_count",
    }
    for needle in ("NEVER_EXPOSE_HASH", "PRIVATE_NOTE_CONTENT", "oauth_accounts"):
        assert needle not in json.dumps(data)
    assert (await client.get("/api/admin/users", params={"q": "%"})).json()["total"] == 1
    assert (await client.get("/api/admin/users", params={"q": str(owners[1])})).json()["total"] == 1
    assert (await client.get("/api/admin/users", params={"per_page": 101})).status_code == 422
    assert (
        await client.get("/api/admin/users", params={"sort": "hashed_password"})
    ).status_code == 422
    assert (await client.get(f"/api/admin/users/{uuid4()}")).status_code == 404
    assert (await client.delete(f"/api/admin/users/{owners[0]}")).status_code == 405
    from src.main import app as public_app

    assert not any("admin" in route for route in public_app.openapi()["paths"])
    assert not any("documents" in route for route in app.openapi()["paths"])


async def test_summary_deduplicates_inventory_audio_imports_and_extractor_children(env):
    sessions, owners, root, client = env
    await original(env)
    await original(env, index=0, source="pwa_audio", operation="upload_audio")
    imported = await original(env, index=1, source="pwa_note", operation="import_document")
    # Original date predates import; arrival is the accepted import timestamp.
    store = FileDocumentStore(root / str(owners[1]) / "documents")
    path = root / str(owners[1]) / "documents" / f"{imported.id}.json"
    payload = imported.model_dump(mode="json")
    payload["created_at"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(payload))
    await store.get(imported.id)
    parent = uuid4()
    async with sessions.begin() as session:
        session.add(
            ProcessingRecord(
                id=parent,
                user_id=owners[0],
                workflow="document",
                resource_kind="document",
                resource_id=uuid4(),
                status="completed",
                stage="done",
                config={},
                checkpoints={},
            )
        )
        await session.flush()
        session.add(
            ProcessingRecord(
                user_id=owners[0],
                workflow="extractor",
                parent_processing_id=parent,
                extractor_name="test",
                extraction_run_id=uuid4(),
                resource_kind="document",
                resource_id=uuid4(),
                status="failed",
                stage="done",
                config={},
                checkpoints={},
            )
        )
    sync = SyncInventory(sessions, root)
    assert (await sync.run())["documents"] == 3
    assert (await sync.run())["documents"] == 3
    summary = (await client.get("/api/admin/dashboard/summary?period_days=7")).json()
    assert summary["notes_total"] == 3
    assert summary["notes_created"] == 2
    assert summary["notes_by_source"] == {"writing": 1, "audio": 1, "imported": 1}
    assert summary["users_wrote"] == 1
    assert summary["processing"]["completed"] == 1
    assert summary["processing"]["failed"] == 0
    assert summary["users_accessed"] is None
    series = (await client.get("/api/admin/dashboard/activity?period_days=7")).json()["items"]
    assert len(series) == 7 and series[-1]["wrote"] == 1
    assert all(point["accessed"] is None for point in series)
    assert (await client.get("/api/admin/dashboard/summary?period_days=8")).status_code == 422


async def test_bad_or_missing_files_invalidate_coverage_without_destroying_index(env):
    sessions, owners, root, client = env
    document = await original(env)
    sync = SyncInventory(sessions, root)
    await sync.run()
    path = root / str(owners[0]) / "documents" / f"{document.id}.json"
    old = path.read_text()
    path.write_text('{"content":"private malformed data"')
    assert (await sync.run())["failed"] == 1
    summary = (await client.get("/api/admin/dashboard/summary")).json()
    assert summary["notes_total"] is None
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentMetric)) == 1
        assert not (await session.get(DocumentMetric, (owners[0], document.id))).deleted
    path.write_text(old)
    assert (await sync.run())["failed"] == 0
    path.unlink()
    # A normal delete leaves the documents directory present.
    assert (await sync.run())["failed"] == 0
    summary = (await client.get("/api/admin/dashboard/summary")).json()
    assert summary["notes_total"] == 0
    assert summary["notes_created"] == 1  # Historical creation survives deletion.
    path.parent.rmdir()
    assert (await sync.run())["failed"] == 1
    assert (await client.get("/api/admin/users")).json()["items"][0]["notes_count"] is None


async def test_unknown_dates_and_stale_inventory_are_not_zero(env):
    sessions, owners, root, client = env
    await original(env, operation=None)
    await SyncInventory(sessions, root).run()
    summary = (await client.get("/api/admin/dashboard/summary")).json()
    assert summary["notes_total"] == 1
    assert summary["notes_created"] is None and not summary["coverage"]["notes_complete"]
    async with sessions.begin() as session:
        await session.execute(
            update(InventoryState).values(synced_at=datetime.now(UTC) - timedelta(hours=1))
        )
    assert (await client.get("/api/admin/dashboard/summary")).json()["notes_total"] is None


async def test_access_is_idempotent_monotonic_and_bucketed_in_buenos_aires(env):
    sessions, owners, root, client = env
    # 01:00 UTC belongs to the preceding local day.
    later = datetime(2026, 10, 16, 1, tzinfo=UTC)
    await record_access(sessions, owners[0], later)
    await record_access(sessions, owners[0], later - timedelta(minutes=5))
    async with sessions() as session:
        rows = (await session.scalars(select(UserActivity))).all()
        assert len(rows) == 1
        assert rows[0].day.isoformat() == "2026-10-15"
        assert rows[0].last_seen_at == later
        result = await AdministrationRepository(session, now=later).summary(7)
        assert result.users_accessed == 1
    assert period_start(later, 7).isoformat() == "2026-10-09T03:00:00+00:00"


async def test_parallel_sync_does_not_overwrite_checkpoints(env):
    sessions, _, root, _ = env
    async with sessions() as session:
        assert await session.scalar(select(func.pg_try_advisory_lock(LOCK_ID)))
        try:
            assert (await SyncInventory(sessions, root).run())["status"] == "busy"
        finally:
            await session.execute(select(func.pg_advisory_unlock(LOCK_ID)))


async def test_migration_preserves_unknown_historical_dates_and_existing_sessions():
    import subprocess
    import sys

    from sqlalchemy.engine import make_url

    configured = make_url(os.environ["ADMIN_TEST_DATABASE_URL"])
    assert configured.database.startswith("admin_test")
    database = f"admin_test_migration_{uuid4().hex}"
    administrator = create_async_engine(
        configured.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    engine = None
    async with administrator.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        target = configured.set(database=database).render_as_string(hide_password=False)

        def migrate(revision):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", revision],
                env={**os.environ, "DATABASE_URL": target},
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr

        migrate("20261015_10")
        engine = create_async_engine(target)
        owner = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    'INSERT INTO "user" '
                    '(id,email,hashed_password,is_active,is_superuser,is_verified) '
                    "VALUES (:id,'legacy@example.com','unused',true,false,false)"
                ),
                {"id": owner},
            )
            await connection.execute(
                text(
                    "INSERT INTO accesstoken(token,user_id,created_at,session_version) "
                    "VALUES ('legacy-test-token',:id,now(),0)"
                ),
                {"id": owner},
            )
        migrate("head")
        async with engine.begin() as connection:
            assert await connection.scalar(text('SELECT created_at FROM "user"')) is None
            assert await connection.scalar(text("SELECT count(*) FROM accesstoken")) == 1
            await connection.execute(
                text(
                    'INSERT INTO "user" '
                    '(id,email,hashed_password,is_active,is_superuser,is_verified) '
                    "VALUES (:id,'new@example.com','unused',true,false,false)"
                ),
                {"id": uuid4()},
            )
            assert await connection.scalar(
                text("SELECT created_at IS NOT NULL FROM \"user\" WHERE email='new@example.com'")
            )
    finally:
        if engine:
            await engine.dispose()
        async with administrator.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await administrator.dispose()
