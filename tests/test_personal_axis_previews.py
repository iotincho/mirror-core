"""Preview recovery and expiration with memory ports, without SQL, paths or providers."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest

from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.personal_axes.models import PreviewRequest
from src.core.extractors.personal_axes.previews import PreviewConfiguration, PreviewLocation
from src.core.processing.errors import WorkflowFailure
from src.core.processing.models import ProcessingJob, SubmissionReceipt
from src.use_cases.personal_axes.expire_previews import ExpireAxisPreviews
from src.use_cases.personal_axes.previews import AxisPreviews
from src.use_cases.personal_axes.process_preview import ProcessAxisPreview


@pytest.fixture
def anyio_backend():
    return "asyncio"


class MemoryFiles:
    def __init__(self, preview_id, events):
        self.id, self.values, self.events = preview_id, {}, events
        self.layers = SimpleNamespace(get=AsyncMock(return_value=None))

    def run_id(self, document_id):
        return uuid5(self.id, f"document:{document_id}")

    async def read(self, name):
        return deepcopy(self.values.get(name))

    async def write(self, name, value):
        assert name not in self.values or self.values[name] == value
        self.events.append(name)
        self.values[name] = deepcopy(value)

    async def delete(self):
        self.values.clear()


class MemoryPreviews:
    def __init__(self, owner, clock):
        self.owner, self.now = owner, clock
        self.files, self.jobs, self.receipts, self.events = {}, {}, {}, []
        self.interrupt, self.busy = False, set()

    def for_owner(self, owner):
        assert owner == self.owner
        return self

    def for_preview(self, preview_id):
        return self.files.setdefault(preview_id, MemoryFiles(preview_id, self.events))

    async def candidates(self, limit):
        return [PreviewLocation(self.owner, key) for key in list(self.files)[:limit]]

    @asynccontextmanager
    async def guard(self, owner, preview_id):
        assert owner == self.owner
        yield preview_id not in self.busy

    @asynccontextmanager
    async def sources(self, owner, ids, *, shared=False):
        assert owner == self.owner
        yield True

    async def get(self, owner, preview_id):
        assert owner == self.owner
        return self.jobs.get(preview_id)

    async def receipt(self, owner, operation, key):
        assert owner == self.owner
        return self.receipts.get((operation, key))

    @asynccontextmanager
    async def reservation(self, owner, max_pending):
        assert owner == self.owner
        pending = []

        async def enqueue(preview_id, key, request_hash, sources, expires_at):
            self.events.append("enqueue")
            assert await self.for_preview(preview_id).read("input")
            if self.interrupt:
                raise ConnectionError("synthetic interrupted transaction")
            pending.append((preview_id, key, request_hash, expires_at))

        yield SimpleNamespace(now=self.now(), enqueue=enqueue)
        for preview_id, key, request_hash, expires_at in pending:
            self.jobs[preview_id] = ProcessingJob(
                id=preview_id,
                user_id=owner,
                resource_kind="axis_preview",
                resource_id=preview_id,
                workflow="axis_preview",
                stage="prompt_generation",
                expires_at=expires_at,
            )
            self.receipts["axis_preview", key] = SubmissionReceipt(
                user_id=owner,
                operation="axis_preview",
                key=key,
                request_hash=request_hash,
                resource_kind="axis_preview",
                resource_id=preview_id,
            )

    async def expired(self, limit):
        return [job for job in self.jobs.values() if job.expires_at <= self.now()][:limit]

    async def remove(self, owner, preview_id):
        assert owner == self.owner
        del self.jobs[preview_id]


@pytest.fixture
def preview():
    owner, now = uuid4(), datetime.now(UTC)
    clock = lambda: now  # noqa: E731
    storage = MemoryPreviews(owner, clock)
    documents = [build_document(NewDocument(content=f"Idea sintética {i}.")) for i in range(5)]
    originals = SimpleNamespace(
        get=AsyncMock(
            side_effect=lambda key: next(document for document in documents if document.id == key)
        )
    )
    case = AxisPreviews(
        owner,
        originals,
        storage,
        storage,
        SimpleNamespace(approved=AsyncMock(return_value=None)),
        PreviewConfiguration("openai", "fixture-model", 6000, 100000, 20, 72),
        clock,
    )
    return SimpleNamespace(**locals())


def request(env, count=1):
    return PreviewRequest(
        draft_id=uuid4(),
        revision=1,
        title="Ideas",
        purpose="Recuperar ideas",
        document_ids=[document.id for document in env.documents[:count]],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("count", [1, 3, 5])
async def test_sample_is_written_before_executable_work_and_replay_is_identical(preview, count):
    env, key = preview, uuid4()
    body = request(env, count)
    first = await env.case.request(body, key)
    assert len(first["notes"]) == count
    assert env.storage.events == ["input", "enqueue"]
    assert await env.case.request(body, key) == first
    assert env.storage.events == ["input", "enqueue"]
    assert len(env.storage.jobs) == len(env.storage.receipts) == 1


@pytest.mark.anyio
async def test_interrupted_transaction_reuses_exact_orphan_configuration(preview):
    env, key = preview, uuid4()
    body = request(env)
    env.storage.interrupt = True
    with pytest.raises(ConnectionError):
        await env.case.request(body, key)
    assert not env.storage.jobs and not env.storage.receipts
    preview_id = uuid5(env.owner, f"axis-preview:{key}")
    before = await env.storage.for_preview(preview_id).read("input")
    env.storage.interrupt = False
    env.case.configuration = replace(env.case.configuration, model="another-model")
    await env.case.request(body, key)
    assert await env.storage.for_preview(preview_id).read("input") == before
    assert before["configuration"]["model"] == "fixture-model"


@pytest.mark.anyio
async def test_cleanup_preserves_locked_jobs_and_blocks_late_worker(preview):
    env = preview
    first = await env.case.request(request(env), uuid4())
    second = await env.case.request(request(env), uuid4())
    first_id, second_id = (
        next(key for key in env.storage.jobs if str(key) == item["id"]) for item in (first, second)
    )
    env.storage.busy.add(second_id)
    expired = lambda: env.now + timedelta(hours=73)  # noqa: E731
    env.storage.now = expired
    await ExpireAxisPreviews(env.storage, env.storage, expired).execute()
    assert first_id not in env.storage.jobs and second_id in env.storage.jobs
    assert not env.storage.files[first_id].values and env.storage.files[second_id].values
    env.case.clock = expired

    @asynccontextmanager
    async def scope(owner):
        assert owner == env.owner
        yield env.case

    def unexpected_provider(_):
        pytest.fail("Late delivery must not invoke a provider")

    worker = ProcessAxisPreview(scope, unexpected_provider, None, 2)
    context = SimpleNamespace(
        record=ProcessingJob(
            id=first_id,
            user_id=env.owner,
            resource_kind="axis_preview",
            resource_id=first_id,
            workflow="axis_preview",
            stage="prompt_generation",
        )
    )
    with pytest.raises(WorkflowFailure, match="axis_preview_not_found"):
        await worker.execute(context)
    assert not env.storage.files[first_id].values


@pytest.mark.anyio
async def test_cleanup_waits_for_orphan_ttl_then_removes_input_without_sql(preview):
    env, key = preview, uuid4()
    env.storage.interrupt = True
    with pytest.raises(ConnectionError):
        await env.case.request(request(env), key)
    preview_id = uuid5(env.owner, f"axis-preview:{key}")
    await ExpireAxisPreviews(env.storage, env.storage, env.clock).execute()
    assert env.storage.files[preview_id].values
    assert not env.storage.jobs
    await ExpireAxisPreviews(
        env.storage, env.storage, lambda: env.now + timedelta(hours=73)
    ).execute()
    assert not env.storage.files[preview_id].values


@pytest.mark.anyio
async def test_orphan_directory_scan_is_bounded_and_rotates_past_invalid_names(tmp_path):
    from src.adapters.storage.filesystem.personal_axes.cleanup import PreviewRoots

    owner, ids = uuid4(), {uuid4() for _ in range(5)}
    root = tmp_path / str(owner) / "laboratory" / "previews"
    for preview_id in ids | {"invalid"}:
        (root / str(preview_id)).mkdir(parents=True)
    roots, found = PreviewRoots(tmp_path), set()
    for _ in range(4):
        candidates = await roots.candidates(2)
        assert len(candidates) <= 2
        assert all(item.owner == owner for item in candidates)
        found.update(item.preview_id for item in candidates)
    assert found == ids


@pytest.mark.anyio
async def test_http_preserves_missing_source_code_and_contextual_status(preview):
    import httpx
    from fastapi import FastAPI

    from src.adapters.access.api.public.personal_axes.preview_routes import build_router
    from src.core.extractors.personal_axes.models import AxisError
    from src.core.extractors.personal_axes.previews import SampleSourceUnavailable

    async def same_origin():
        pass

    case = SimpleNamespace(
        request=AsyncMock(side_effect=SampleSourceUnavailable()),
        snapshot=AsyncMock(side_effect=AxisError("axis_source_unavailable")),
    )
    app = FastAPI()
    app.include_router(build_router(lambda: case, same_origin))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as api:
        response = await api.post(
            "/laboratory/axis-previews",
            json=request(preview).model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "axis_source_unavailable"}
        response = await api.get(f"/laboratory/axis-previews/{uuid4()}")
        assert response.status_code == 409
        assert response.json() == {"detail": "axis_source_unavailable"}
