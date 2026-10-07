"""Mass migration tests against isolated PostgreSQL and newly created ArcadeDB databases."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from legacy_graph_fixture import EmbeddingSpec, legacy_schema_statements
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.documents import NewDocument, build_document
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.maintenance.data_migrations import DataMigrations
from src.maintenance.models import DataMigration
from src.processing.models import ProcessingEvent, ProcessingOutbox, ProcessingRecord
from src.processing.repository import ProcessingRepository
from src.services.document_store import FileDocumentStore
from src.user_management.models import User
from src.workspaces.models import UserWorkspace

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.getenv("PROCESSING_TEST_DATABASE_URL") and os.getenv("CLEANUP_TEST_ARCADEDB_URL")),
        reason="requires isolated PostgreSQL and ArcadeDB",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def population(tmp_path):
    url = os.environ["CLEANUP_TEST_ARCADEDB_URL"]
    password = os.environ["CLEANUP_TEST_ARCADEDB_PASSWORD"]
    engine = create_async_engine(os.environ["PROCESSING_TEST_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    instance = f"migration-{uuid4().hex}"
    settings = SimpleNamespace(
        arcadedb_http_url=url,
        arcadedb_username="root",
        arcadedb_password=password,
        arcadedb_instance_key=instance,
        workspaces_path=tmp_path / "workspaces",
        processing_lease_seconds=90,
    )
    runner = DataMigrations(sessions, settings)
    owners, databases, clients, documents = [], [], {}, {}
    async with httpx.AsyncClient(base_url=url, auth=("root", password)) as admin:
        try:
            # Include a suspended workspace and an empty pending registration automatically.
            for status in ("active", "suspended", "pending"):
                owner = uuid4()
                name = f"migration_test_{owner.hex}"
                owners.append(owner)
                async with sessions.begin() as session:
                    session.add(
                        User(id=owner, email=f"{owner}@test.local", hashed_password="unused")
                    )
                    await session.flush()
                    session.add(
                        UserWorkspace(
                            user_id=owner,
                            arcadedb_instance_key=instance,
                            database_name=name,
                            graph_username=f"user_{owner.hex}",
                            graph_secret_ciphertext="not needed for administrative migration",
                            status="pending" if status == "pending" else "active",
                        )
                    )
                if status == "pending":
                    continue
                (
                    await admin.post("/api/v1/server", json={"command": f"create database {name}"})
                ).raise_for_status()
                databases.append(name)
                client = AsyncArcadeDBHTTPClient(url, name, "root", password)
                clients[owner] = client
                for statement in legacy_schema_statements(
                    EmbeddingSpec(provider="fake", model="test", dimensions=3)
                ):
                    await client.command(statement)
                root = settings.workspaces_path / str(owner)
                document = build_document(NewDocument(content=f"Original {owner}", source="test"))
                await FileDocumentStore(root / "documents").save(document)
                documents[owner] = document
                await client.command("CREATE VERTEX Document SET id=:id", {"id": str(document.id)})
                await client.command(
                    "CREATE VERTEX Claim SET id=:id, document_id=:document",
                    {"id": str(uuid4()), "document": str(document.id)},
                )
                for name in ("a.json", "b.json"):
                    file = root / "extractions" / name
                    file.parent.mkdir(exist_ok=True)
                    file.write_text("old result")
                repo = ProcessingRepository(sessions, 90)
                await repo.create(
                    user_id=owner,
                    workflow="document",
                    stage="extraction",
                    resource_kind="document",
                    resource_id=document.id,
                    config={},
                )
                if status == "suspended":
                    async with sessions.begin() as session:
                        await session.execute(
                            update(UserWorkspace)
                            .where(UserWorkspace.user_id == owner)
                            .values(status=status)
                        )
            yield SimpleNamespace(
                runner=runner,
                sessions=sessions,
                owners=owners,
                clients=clients,
                documents=documents,
                settings=settings,
            )
        finally:
            for client in clients.values():
                await client.close()
            for name in databases:
                (
                    await admin.post("/api/v1/server", json={"command": f"drop database {name}"})
                ).raise_for_status()
            async with sessions.begin() as session:
                await session.execute(
                    delete(DataMigration).where(DataMigration.instance_key == instance)
                )
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
                await session.execute(
                    delete(UserWorkspace).where(UserWorkspace.user_id.in_(owners))
                )
                await session.execute(delete(User).where(User.id.in_(owners)))
            await engine.dispose()


async def test_bulk_discovers_all_statuses_and_repeated_deploy_is_noop(population):
    env = population
    dry = await env.runner.run()
    assert len(dry["workspaces"]) == 3
    assert (await env.runner.state("__all__")) is None
    for client in env.clients.values():
        assert (await client.query("SELECT FROM Claim"))["result"]
    result = await env.runner.run(apply=True, services_stopped=True)
    assert result["status"] == "completed" and len(result["workspaces"]) == 3
    for owner, client in env.clients.items():
        assert not (await client.query("SELECT FROM Claim"))["result"]
        assert (await client.query("SELECT content FROM Document"))["result"] == [
            {"content": env.documents[owner].content}
        ]
        assert (
            await FileDocumentStore(env.settings.workspaces_path / str(owner) / "documents").get(
                env.documents[owner].id
            )
        ).content == env.documents[owner].content
        assert (env.runner.backup_path(SimpleNamespace(user_id=owner)) / "backup.ready").exists()
    async with env.sessions() as session:
        statuses = (
            await session.scalars(
                select(UserWorkspace.status).where(UserWorkspace.user_id.in_(env.owners))
            )
        ).all()
        assert set(statuses) == {"active", "suspended", "pending"}
        jobs = (
            await session.scalars(
                select(ProcessingRecord).where(ProcessingRecord.user_id.in_(env.owners))
            )
        ).all()
        assert all(j.workflow_version == 2 and j.stage == "document_persistence" for j in jobs)
    assert (await env.runner.run(apply=True, services_stopped=True))["status"] == "already_applied"


async def test_resume_after_graph_commit_and_partial_file_deletion(population, monkeypatch):
    env = population
    original_unlink = Path.unlink
    failed = False

    def interrupted_unlink(path, *args, **kwargs):
        nonlocal failed
        if (
            path.name == "b.json"
            and "extractions" in path.parts
            and "files" not in path.parts
            and not failed
        ):
            failed = True
            raise RuntimeError("simulated crash after graph commit")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted_unlink)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await env.runner.run(apply=True, services_stopped=True)
    assert (await env.runner.state("__all__")).status == "running"
    result = await env.runner.run(apply=True, services_stopped=True)
    assert result["status"] == "completed"
    for client in env.clients.values():
        assert not (await client.query("SELECT FROM Claim"))["result"]


async def test_resume_after_backfill_before_workspace_checkpoint(population, monkeypatch):
    env = population
    first = next(w.user_id for w in await env.runner.discover() if w.user_id in env.clients)
    original_save, failed = env.runner.save, False

    async def interrupted_save(target, status, details):
        nonlocal failed
        if str(target) == str(first) and status == "completed" and not failed:
            failed = True
            raise RuntimeError("simulated checkpoint failure")
        return await original_save(target, status, details)

    monkeypatch.setattr(env.runner, "save", interrupted_save)
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        await env.runner.run(apply=True, services_stopped=True)
    assert (await env.runner.run(apply=True, services_stopped=True))["status"] == "completed"
    assert (await env.runner.state("__all__")).status == "completed"


async def test_migration_lock_and_missing_original_block_completion(population):
    env = population
    async with env.runner.lock():
        with pytest.raises(ValueError, match="Another data migration"):
            await env.runner.run(apply=True, services_stopped=True)
    owner = next(iter(env.documents))
    path = (
        env.settings.workspaces_path / str(owner) / "documents" / f"{env.documents[owner].id}.json"
    )
    path.unlink()
    with pytest.raises(ValueError, match="without originals"):
        await env.runner.run(apply=True, services_stopped=True)
    assert (await env.runner.state("__all__")).status == "running"
    with pytest.raises(ValueError, match="stopped API"):
        await env.runner.run(apply=True)


async def test_recovers_interrupted_child_and_failed_audio_without_losing_transcript(population):
    env = population
    owner = env.owners[0]
    repo = ProcessingRepository(env.sessions, 90)
    parent = await repo.create(
        user_id=owner,
        workflow="audio",
        stage="document_processing",
        resource_kind="audio",
        resource_id=env.documents[owner].id,
        config={},
    )
    async with env.sessions.begin() as session:
        child = await session.scalar(
            select(ProcessingRecord).where(
                ProcessingRecord.user_id == owner, ProcessingRecord.workflow == "document"
            )
        )
        child_id, old_generation = child.id, child.generation
        child.status, child.lease_owner = "running", "old-worker"
        child.parent_processing_id = parent.id
        audio = await session.get(ProcessingRecord, parent.id)
        audio.status, audio.error_code = "failed", "document_processing_failed"
        audio.child_processing_id = child.id
        audio.checkpoints = {"transcription": {"artifact": "transcript.json"}}
    await env.runner.run(apply=True, services_stopped=True)
    async with env.sessions() as session:
        child = await session.get(ProcessingRecord, child_id)
        audio = await session.get(ProcessingRecord, parent.id)
        assert child.status == "queued" and child.workflow_version == 2
        assert child.lease_owner is None and child.generation > old_generation
        assert audio.status == "waiting" and audio.error_code is None
        assert audio.checkpoints == {"transcription": {"artifact": "transcript.json"}}


async def test_empty_partially_provisioned_database_does_not_block_deployment(population):
    env = population
    owner = env.owners[2]
    workspace = next(w for w in await env.runner.discover() if w.user_id == owner)
    root = env.settings.workspaces_path / str(owner)
    async with httpx.AsyncClient(
        base_url=env.settings.arcadedb_http_url, auth=("root", env.settings.arcadedb_password)
    ) as admin:
        (
            await admin.post(
                "/api/v1/server", json={"command": f"create database {workspace.database_name}"}
            )
        ).raise_for_status()
        try:
            dry = await env.runner.run()
            assert len(dry["workspaces"]) == 3 and not root.exists()
            result = await env.runner.run(apply=True, services_stopped=True)
            assert result["status"] == "completed"
            async with env.sessions() as session:
                saved = await session.get(UserWorkspace, owner)
                assert saved.status == "pending"
        finally:
            (
                await admin.post(
                    "/api/v1/server", json={"command": f"drop database {workspace.database_name}"}
                )
            ).raise_for_status()
