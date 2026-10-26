"""Real allocation/locks and ArcadeDB principals on explicitly disposable services."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.workspaces import PostgresWorkspaces
from src.bootstrap.settings import Settings
from src.bootstrap.workspaces import (
    ConfiguredCipher,
    build_provisioner,
    build_workspace_runtime,
    workspace_binding,
)
from src.core.domain.documents import NewDocument, build_document
from src.core.workspaces.models import WorkspaceStatus
from src.use_cases.workspaces.access import WorkspaceAccess

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.getenv("WORKSPACE_TEST_DATABASE_URL") and os.getenv("WORKSPACE_TEST_ARCADEDB_URL")),
        reason="requires disposable workspace_test PostgreSQL and ArcadeDB",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def workspace_env(tmp_path):
    engine = create_async_engine(os.environ["WORKSPACE_TEST_DATABASE_URL"], hide_parameters=True)
    if not engine.url.database.startswith("workspace_test"):
        raise RuntimeError("Workspace tests require a disposable workspace_test database")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        DATABASE_URL=os.environ["WORKSPACE_TEST_DATABASE_URL"],
        ARCADEDB_HTTP_URL=os.environ["WORKSPACE_TEST_ARCADEDB_URL"],
        ARCADEDB_USERNAME="root",
        ARCADEDB_ROOT_PASSWORD=os.environ["WORKSPACE_TEST_ARCADEDB_PASSWORD"],
        AUTH_SESSION_SECRET="workspace-provisioning-synthetic-secret",
        WORKSPACE_SECRET_KEY=None,
        WORKSPACES_PATH=tmp_path,
    )
    if settings.arcadedb_http_url != os.environ["WORKSPACE_TEST_ARCADEDB_URL"]:
        raise RuntimeError("Workspace fixture cannot use inherited service configuration")
    owners = [uuid4(), uuid4()]
    async with sessions.begin() as sql:
        for owner in owners:
            sql.add(User(id=owner, email=f"{owner}@example.test", hashed_password="synthetic"))
    store = PostgresWorkspaces(sessions)
    provisioner = build_provisioner(sessions, settings)
    access = WorkspaceAccess(
        store, ConfiguredCipher(settings), settings.arcadedb_instance_key, provisioner
    )
    try:
        yield SimpleNamespace(
            owners=owners,
            sessions=sessions,
            settings=settings,
            store=store,
            provisioner=provisioner,
            access=access,
        )
    finally:
        # Only databases allocated to this fixture; the server itself is disposable.
        async with httpx.AsyncClient(
            base_url=settings.arcadedb_http_url,
            auth=(settings.arcadedb_username, settings.arcadedb_password),
        ) as admin:
            for owner in owners:
                workspace = await store.read(owner)
                if workspace is not None:
                    response = await admin.post(
                        "/api/v1/server",
                        json={
                            "command": f"drop database {workspace.database_name}",
                        },
                    )
                    # An allocation test may stop before creating the remote database.
                    assert response.status_code in {200, 400, 404}
        async with sessions.begin() as sql:
            await sql.execute(delete(User).where(User.id.in_(owners)))
        await engine.dispose()


async def test_provisioned_principals_and_originals_are_isolated_by_verified_owner(workspace_env):
    env = workspace_env
    runtimes = []
    try:
        for owner in env.owners:
            assert await env.access.prepare(owner) == "active"
            resolved = await env.access.resolve(owner)
            assert resolved.workspace.status == WorkspaceStatus.ACTIVE
            assert resolved.graph_secret not in repr(resolved)
            runtimes.append(
                build_workspace_runtime(workspace_binding(resolved, env.settings), env.settings)
            )
        first, second = runtimes
        original = build_document(NewDocument(content="Synthetic workspace isolation evidence."))
        await first.document_store.save(original)
        await first.graph_store.persist_document(original)
        assert await first.document_store.list() == [original]
        assert await second.document_store.list() == []
        for runtime, expected in ((first, [{"id": str(original.id)}]), (second, [])):
            result = await runtime.graph_store.database_client.query("SELECT id FROM Document")
            assert result["result"] == expected
            owner = runtime.context.user_id
            secret = (await env.access.resolve(owner)).graph_secret
            async with httpx.AsyncClient(auth=(runtime.context.graph_username, secret)) as client:
                response = await client.get(env.settings.arcadedb_http_url + "/api/v1/databases")
                response.raise_for_status()
                assert response.json()["result"] == [runtime.context.database_name]
    finally:
        for runtime in runtimes:
            await runtime.graph_store.close()


async def test_concurrent_existing_allocation_and_suspension_do_not_reprovision(workspace_env):
    env = workspace_env
    owner = env.owners[0]
    async with env.store.transaction() as transaction:
        allocation = await transaction.get_or_create(
            owner,
            arcadedb_instance_key=env.settings.arcadedb_instance_key,
            graph_secret_ciphertext=ConfiguredCipher(env.settings).encrypt("synthetic-secret"),
        )
    remote = env.provisioner.remote.provision
    env.provisioner.remote.provision = AsyncMock(side_effect=remote)
    await asyncio.gather(env.provisioner.provision(owner), env.provisioner.provision(owner))
    assert env.provisioner.remote.provision.await_count == 1
    active = await env.store.read(owner)
    assert active.status == WorkspaceStatus.ACTIVE
    assert active.database_name == allocation.database_name
    assert active.graph_secret_ciphertext == allocation.graph_secret_ciphertext
    async with env.store.transaction() as transaction:
        suspended = await transaction.get(owner, for_update=True)
        suspended.status = WorkspaceStatus.SUSPENDED
    assert await env.access.prepare(owner) == "suspended"
    assert (await env.provisioner.provision(owner, force=True)).status == "suspended"
    assert env.provisioner.remote.provision.await_count == 1
