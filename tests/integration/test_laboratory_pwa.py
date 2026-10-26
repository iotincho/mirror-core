"""Opt-in PWA against real HTTP, SQL, workers and graph; deterministic providers only."""

# ruff: noqa: F811
import asyncio
import contextlib
import os
import secrets
import socket

import pytest
import uvicorn
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update
from test_axis_previews import Provider
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run  # noqa: F401
from test_personal_axis_processing import active  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.adapters.access.api.public.routes import processing
from src.adapters.storage.postgres.accounts import AccessToken, User
from src.adapters.storage.postgres.models import ProcessingRecord
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.auth import router as auth_router
from src.bootstrap.database import get_async_session
from src.bootstrap.processing import get_repository
from src.bootstrap.public_channels import activity_router
from src.bootstrap.public_dependencies import get_public_processing, get_upload_limits
from src.bootstrap.settings import get_settings
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.domain.documents import NewDocument, build_document
from src.core.processing.errors import ResourceBusy
from src.extractors.personal_axes.contracts import AxisError
from src.extractors.personal_axes.dependencies import get_axis_previews
from src.extractors.personal_axes.history_models import AxisHistoryBatch
from src.extractors.personal_axes.routes import router as axes_router
from src.use_cases.process_axis_history import ProcessAxisHistory
from src.use_cases.process_axis_preview import ProcessAxisPreview

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not all(
            os.getenv(key)
            for key in (
                "PROCESSING_TEST_DATABASE_URL",
                "EMOTIONS_TEST_ARCADEDB_URL",
                "LABORATORY_PWA_DIST",
                "LABORATORY_LIVE_BROWSER",
            )
        ),
        reason="requires disposable databases, built PWA and browser script",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_browser_real_laboratory_cycle(active, monkeypatch):
    env = active
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_session_secret", "laboratory-http-integration-secret")
    monkeypatch.setattr(settings, "openai_model", "test-model")
    monkeypatch.setattr(settings, "platform_activity_enabled", False)
    provider = Provider()
    legacy = env.registry.definitions[("document", 3)].run.__self__
    env.registry.register(
        "axis_preview",
        1,
        ProcessAxisPreview(legacy.runtime_factory, lambda _: provider, settings).definition,
    )
    env.registry.register(
        "axis_history_note",
        1,
        ProcessAxisHistory(
            legacy.runtime_factory,
            env.registry.definitions[("extractor", 1)].run.__self__.extractor_factory,
        ).definition,
    )
    for index in range(6):
        document = build_document(NewDocument(content=env.original.content)).model_copy(
            update={"title": f"Nota de integración {index + 1}"}
        )
        await env.runtime.document_store.save(document)
    await env.runtime.document_store.update_title(env.original.id, "Nota original")

    async def session():
        async with env.repo.sessions() as sql:
            yield sql

    async def runtime():
        yield env.runtime

    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: env.repo
    protected = APIRouter(prefix="/api", dependencies=[Depends(get_authenticated_user)])
    protected.include_router(axes_router)
    protected.include_router(processing.build_router(get_public_processing, get_upload_limits))
    protected.include_router(activity_router)

    # Shell dependencies do not participate in the Laboratory domain under test.
    @protected.get("/workspace/status")
    async def workspace():
        return {"status": "active"}

    @protected.get("/notifications/summary")
    async def summary():
        return {"unread_count": 0}

    @protected.post("/notifications/bootstrap", status_code=204)
    async def bootstrap():
        return None

    app.include_router(auth_router, prefix="/api")
    app.include_router(protected)
    app.dependency_overrides[get_async_session] = session
    app.dependency_overrides[get_workspace_runtime] = runtime
    app.dependency_overrides[get_axis_previews] = lambda: env.previews

    @app.exception_handler(AxisError)
    async def axis_error(_, error):
        return JSONResponse({"detail": error.code}, status_code=error.status)

    app.mount("/", StaticFiles(directory=os.environ["LABORATORY_PWA_DIST"], html=True))
    async with env.repo.sessions.begin() as sql:
        await sql.execute(
            update(User).where(User.id == env.owner).values(email=f"{env.owner}@example.com")
        )
    token = secrets.token_urlsafe(32)
    async with env.repo.sessions.begin() as sql:
        sql.add(AccessToken(token=token, user_id=env.owner, session_version=0))

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    server_task = asyncio.create_task(server.serve(sockets=[sock]))

    async def workers():
        while True:
            async with env.repo.sessions() as sql:
                records = list(
                    (
                        await sql.scalars(
                            select(ProcessingRecord)
                            .where(
                                ProcessingRecord.user_id == env.owner,
                                ProcessingRecord.status.in_(["queued", "retrying", "waiting"]),
                                ProcessingRecord.workflow.in_(
                                    ["axis_preview", "document", "extractor", "axis_history_note"]
                                ),
                            )
                            .order_by(ProcessingRecord.created_at)
                        )
                    ).all()
                )
            for record in records:
                try:
                    await run(env, record)
                except ResourceBusy:
                    # Match the real task adapter: a concurrent API reservation
                    # may hold this resource briefly; retry on the next poll.
                    continue
            await asyncio.sleep(0.05)

    worker = asyncio.create_task(workers())
    try:
        while not server.started:
            if server_task.done():
                await server_task
            await asyncio.sleep(0.02)
        process = await asyncio.create_subprocess_exec(
            "node",
            os.environ["LABORATORY_LIVE_BROWSER"],
            env={
                **os.environ,
                "LABORATORY_LIVE_ORIGIN": f"http://127.0.0.1:{port}",
                "LABORATORY_LIVE_TOKEN": token,
                "LABORATORY_LIVE_CONTENT": env.original.content,
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
        assert process.returncode == 0, output.decode()
        assert len(provider.generations) == 3
        assert len(provider.generations[1]["adjustments"]) == 1
        assert not worker.done(), "deterministic worker stopped during browser flow"
        print(output.decode())
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        server.should_exit = True
        await server_task
        sock.close()
        # The owner fixture deletes this isolated account after all its access tokens.
        async with env.repo.sessions.begin() as sql:
            from sqlalchemy import delete

            await sql.execute(delete(AxisHistoryBatch).where(AxisHistoryBatch.user_id == env.owner))
            await sql.execute(delete(AccessToken).where(AccessToken.user_id == env.owner))
