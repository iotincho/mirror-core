"""Durable application behavior with in-memory ports and no SQL, broker or SDK."""

import subprocess
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.domain.documents import NewDocument, build_document
from src.core.processing.errors import (
    LeaseLost,
    StorageUnavailable,
    WorkflowFailure,
    WorkflowWaiting,
)
from src.core.processing.models import ProcessingJob, SubmissionReceipt
from src.core.processing.submissions import SubmissionConflict
from src.core.processing.workflows import WorkflowDefinition, WorkflowRegistry
from src.use_cases.processing.execute import ExecuteProcessing
from src.use_cases.processing.request_processing import RequestProcessing


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def acquired(*_):
    yield True


def test_application_imports_with_infrastructure_modules_blocked():
    code = """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {
            'sqlalchemy', 'taskiq', 'openai', 'httpx', 'fastapi', 'tiktoken',
            'fastapi_users', 'cryptography',
        }
        if fullname.split('.')[0] in blocked:
            raise AssertionError('Infrastructure imported: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from src.use_cases.processing import execute, request_processing, submit_processing
from src.use_cases.processing import process_extractor, process_document_extractors
from src.use_cases.processing import process_document, process_document_layers
from src.use_cases.documents import backfill_document_titles, archive, delete_document
from src.use_cases.audio import process_audio_note, create_audio_note
from src.use_cases.extraction import emotions, document_embeddings
from src.use_cases.graph import read_graph
from src.core.processing import failures
from src.use_cases.auth import authenticate, recover_password, send_recovery_email
from src.use_cases.workspaces import access, provision
from src.use_cases.exteriorization import configure_invitations, generate_invitation
from src.use_cases.exteriorization import schedule_invitations, send_invitation
from src.use_cases.notifications import center
from src.use_cases.administration import query, sync_inventory, record_access
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["completed", "waiting", "lease_lost", "storage", "retry"])
async def test_runner_resolves_only_durable_outcomes_and_discards_duplicate_delivery(outcome):
    job = ProcessingJob(
        user_id=uuid4(),
        workflow="synthetic",
        resource_kind="document",
        resource_id=uuid4(),
        stage="start",
        stage_attempts=1,
    )
    store = SimpleNamespace(
        lease_seconds=90,
        resource_guard=acquired,
        acquire=AsyncMock(side_effect=[job, None]),
        workspace_active=AsyncMock(return_value=True),
        heartbeat=AsyncMock(),
        finish=AsyncMock(),
        assert_lease=AsyncMock(),
    )
    calls = 0

    async def advance(record, stage, checkpoints):
        record.stage = stage
        record.checkpoints = checkpoints

    store.advance = advance

    async def run(context):
        nonlocal calls
        calls += 1
        if outcome == "waiting":
            raise WorkflowWaiting()
        if outcome == "lease_lost":
            raise LeaseLost()
        if outcome == "storage":
            raise StorageUnavailable()
        if outcome == "retry":
            raise WorkflowFailure("provider_unavailable", retry_delay=10)
        await context.advance("done", artifact="durable")

    registry = WorkflowRegistry()
    registry.register("synthetic", 1, WorkflowDefinition(run, frozenset({("start", "done")})))
    execute = ExecuteProcessing(store, registry)
    if outcome == "storage":
        with pytest.raises(StorageUnavailable):
            await execute(job.id, 1)
    else:
        await execute(job.id, 1)
    await execute(job.id, 1)
    assert calls == 1
    if outcome in {"storage", "waiting", "lease_lost"}:
        store.finish.assert_not_awaited()
    elif outcome == "retry":
        assert store.finish.call_args.kwargs == {
            "status": "retrying",
            "error_code": "provider_unavailable",
            "retry_delay": 10,
            "retryable": True,
        }
    else:
        store.finish.assert_awaited_once_with(job)
        assert job.stage == "done" and job.checkpoints == {"artifact": "durable"}


class MemoryRequests:
    """A transaction port can be implemented without an ORM/session lookalike."""

    def __init__(self):
        self.receipts, self.jobs, self.events, self.outbox = {}, {}, [], []
        self.now = datetime.now(UTC)
        self.interrupt = False

    @asynccontextmanager
    async def transaction(self):
        before = deepcopy((self.receipts, self.jobs, self.events, self.outbox))
        try:
            yield self
        except BaseException:
            self.receipts, self.jobs, self.events, self.outbox = before
            raise

    lock_resource = staticmethod(acquired)
    lock_resources = staticmethod(acquired)

    async def receipt(self, owner, operation, key):
        return self.receipts.get((owner, operation, key))

    async def reserve_mutation(self, owner, operation, key, request_hash, resource_id):
        return self.receipts.setdefault(
            (owner, operation, key),
            SubmissionReceipt(
                user_id=owner,
                operation=operation,
                key=key,
                request_hash=request_hash,
                resource_kind="document",
                resource_id=resource_id,
            ),
        )

    async def job(self, identifier, *, locked=True):
        return self.jobs.get(identifier)

    async def create_jobs(self, jobs):
        self.jobs.update((job.id, job) for job in jobs)

    async def assert_inactive(self, owner, identifier, exclude=()):
        pass

    async def configuration_for(self, owner, baseline):
        return deepcopy(baseline)

    def event(self, job):
        self.events.append(job.id)

    def schedule(self, job):
        self.outbox.append(job.id)
        if self.interrupt and len(self.outbox) == 2:
            raise StorageUnavailable()


@pytest.mark.anyio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_batch_acceptance_replay_and_rollback_share_one_transaction_port(interrupted):
    store = MemoryRequests()
    store.interrupt = interrupted
    documents = [build_document(NewDocument(content=f"Original {index}")) for index in range(2)]
    documents[0] = documents[0].model_copy(update={"title": "Conservar este título"})
    original_by_id = {document.id: document for document in documents}
    originals = SimpleNamespace(get=AsyncMock(side_effect=lambda key: original_by_id[key]))
    baseline = {
        "document_workflow_version": 4,
        "extractors": [
            {"name": "document_title"},
            {"name": "document_embeddings", "force": False},
        ],
    }
    runtime = SimpleNamespace(context=SimpleNamespace(user_id=uuid4()), document_store=originals)
    request = RequestProcessing(store, runtime, workflow_config=lambda: deepcopy(baseline))
    key = uuid4()
    identifiers = [document.id for document in documents]
    if interrupted:
        with pytest.raises(StorageUnavailable):
            await request.reprocess_documents(identifiers, key)
        assert not store.receipts and not store.jobs and not store.events and not store.outbox
        store.interrupt = False
    accepted = await request.reprocess_documents(identifiers, key)
    baseline["extractors"] = []
    replay = await request.reprocess_documents(list(reversed(identifiers)), key)
    assert [job.id for job in replay] == [job.id for job in accepted]
    assert (
        len(store.receipts) == 1 and len(store.jobs) == len(store.events) == len(store.outbox) == 2
    )
    titled = next(job for job in accepted if job.resource_id == documents[0].id)
    assert titled.config["extractors"] == [{"name": "document_embeddings", "force": True}]
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await request.reprocess_documents(identifiers[:1], key)
