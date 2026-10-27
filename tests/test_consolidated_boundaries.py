"""Recovery and isolation across the remaining public/maintenance boundaries."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.adapters.storage.filesystem.migrations import MigrationFiles
from src.adapters.storage.filesystem.owner_originals import FileOwnerOriginals
from src.core.auth.session import SessionExpired, SessionOwner
from src.core.documents.original_access import OriginalStorageUnavailable
from src.core.maintenance.models import MigrationState, MigrationWorkspace, ProcessingHistory
from src.core.processing.reads import ProcessingNotFound
from src.core.workspaces.models import WorkspaceUnavailable
from src.use_cases.auth.authorize_stream import AuthorizeStream
from src.use_cases.documents.resolve_originals import ResolveOriginals
from src.use_cases.maintenance.data_migrations import DataMigrations
from src.use_cases.maintenance.extraction_cleanup import LegacyExtractionCleanup
from src.use_cases.processing.public import PublicProcessing


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_stream_rechecks_revocation_and_workspace_without_a_held_session():
    owner = uuid4()
    lookup = SimpleNamespace(
        lookup=AsyncMock(
            side_effect=[
                SessionOwner(owner, "active", "one"),
                SessionOwner(owner, "suspended", "one"),
                None,
            ]
        )
    )
    authorization = AuthorizeStream(lookup, "one")
    assert await authorization.execute("opaque-cookie") == owner
    with pytest.raises(WorkspaceUnavailable):
        await authorization.execute("opaque-cookie")
    with pytest.raises(SessionExpired):
        await authorization.execute("opaque-cookie")
    with pytest.raises(SessionExpired):
        await authorization.execute(None)
    assert lookup.lookup.await_count == 3


@pytest.mark.anyio
async def test_stream_rejects_a_session_for_another_instance():
    lookup = SimpleNamespace(
        lookup=AsyncMock(return_value=SessionOwner(uuid4(), "active", "other"))
    )
    with pytest.raises(WorkspaceUnavailable):
        await AuthorizeStream(lookup, "current").execute("opaque-cookie")


@pytest.mark.anyio
async def test_public_processing_cannot_read_internal_jobs_or_their_children():
    owner, job = uuid4(), uuid4()
    reads = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(workflow="invitation_push")),
        extractor_children=AsyncMock(),
    )
    case = PublicProcessing(
        SimpleNamespace(context=SimpleNamespace(user_id=owner)), reads, None, None, None, None
    )
    with pytest.raises(ProcessingNotFound):
        await case.children(job)
    reads.get.assert_awaited_once_with(job, owner)
    reads.extractor_children.assert_not_awaited()


@pytest.mark.anyio
async def test_archive_resolution_checks_instance_before_opening_originals():
    originals = SimpleNamespace(documents=AsyncMock())
    workspaces = SimpleNamespace(
        read=AsyncMock(
            return_value=SimpleNamespace(status="suspended", arcadedb_instance_key="other")
        )
    )
    with pytest.raises(WorkspaceUnavailable):
        await ResolveOriginals(workspaces, originals, "current").execute(uuid4())
    originals.documents.assert_not_awaited()


@pytest.mark.anyio
async def test_archive_originals_reject_symlinked_account_directories(tmp_path):
    owner = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / str(owner)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OriginalStorageUnavailable):
        await FileOwnerOriginals(tmp_path).documents(owner)


class Graph:
    def __init__(self):
        self.records = {"Document": [], "Claim": [{"id": "derived"}]}
        self.commits = 0

    async def inventory(self):
        return {
            "schema": [{"name": "Document", "type": "vertex"}, {"name": "Claim", "type": "vertex"}],
            "records": deepcopy(self.records),
        }

    @asynccontextmanager
    async def remove_derived(self, expected):
        before = deepcopy(self.records)
        try:
            self.records["Claim"] = []
            yield
        except BaseException:
            self.records = before
            raise
        else:
            self.commits += 1


@pytest.mark.anyio
async def test_cleanup_resumes_after_graph_commit_and_partial_file_deletion(tmp_path, monkeypatch):
    root, backup = tmp_path / "workspace", tmp_path / "backup"
    (root / "documents").mkdir(parents=True)
    (root / "documents" / "evidence.bin").write_bytes(b"synthetic immutable original")
    (root / "extractions").mkdir()
    for name in ("a.json", "b.json"):
        (root / "extractions" / name).write_text("synthetic derived artifact")
    graph, files = Graph(), MigrationFiles(root)
    case = LegacyExtractionCleanup(graph, files)
    inventory = await case.inventory()
    remove = files.remove_derived

    async def interrupted(expected):
        (root / "extractions" / "a.json").unlink()
        raise OSError("synthetic disk interruption")

    monkeypatch.setattr(files, "remove_derived", interrupted)
    with pytest.raises(OSError):
        await case.apply(backup, inventory, [{"workflow": "document"}], resume=True)
    assert graph.commits == 1 and graph.records["Claim"] == []
    assert (backup / "backup.ready").exists()
    assert not (backup / "cleanup.complete").exists()
    monkeypatch.setattr(files, "remove_derived", remove)
    await case.apply(backup, await case.inventory(), resume=True)
    assert (backup / "cleanup.complete").exists()
    assert (root / "documents" / "evidence.bin").read_bytes() == b"synthetic immutable original"
    assert list((root / "extractions").iterdir()) == []


@pytest.mark.anyio
async def test_changed_original_during_graph_cleanup_rolls_back_graph(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    graph, files = Graph(), MigrationFiles(root)
    case = LegacyExtractionCleanup(graph, files)
    inventory = await case.inventory()
    monkeypatch.setattr(files, "assert_sources", AsyncMock(side_effect=ValueError("changed")))
    with pytest.raises(ValueError, match="changed"):
        await case.apply(tmp_path / "backup", inventory)
    assert graph.commits == 0 and graph.records["Claim"] == [{"id": "derived"}]


@pytest.mark.anyio
async def test_resume_refuses_a_changed_original_even_with_a_complete_backup(tmp_path):
    root = tmp_path / "workspace"
    (root / "documents").mkdir(parents=True)
    original = root / "documents" / "evidence.bin"
    original.write_bytes(b"synthetic original")
    case = LegacyExtractionCleanup(Graph(), MigrationFiles(root))
    backup = tmp_path / "backup"
    await case.apply(backup, await case.inventory(), resume=True)
    original.write_bytes(b"changed original")
    with pytest.raises(ValueError, match="Originals changed"):
        await case.apply(backup, await case.inventory(), resume=True)


@pytest.mark.anyio
async def test_migration_resumes_only_uncommitted_workspace_checkpoints():
    first = MigrationWorkspace(uuid4(), "one", "active")
    second = MigrationWorkspace(uuid4(), "two", "active")
    states, calls = {}, []

    @asynccontextmanager
    async def locked():
        yield

    async def state(target):
        return states.get(target)

    async def save(target, status, details):
        states[target] = MigrationState(status, details)

    class Migration(DataMigrations):
        async def migrate_workspace(self, workspace, *, apply):
            calls.append(workspace.user_id)
            if workspace == second and calls.count(second.user_id) == 1:
                raise OSError("synthetic interruption")
            return {"status": "completed"}

    store = SimpleNamespace(
        lock=locked, state=state, save=save, discover=AsyncMock(return_value=[first, second])
    )
    case = Migration(store, None, "one", None)
    with pytest.raises(ValueError, match="stopped"):
        await case.run(apply=True)
    assert states == {}
    with pytest.raises(OSError):
        await case.run(apply=True, services_stopped=True)
    assert states[first.user_id].status == "completed"
    await case.run(apply=True, services_stopped=True)
    assert calls == [first.user_id, second.user_id, second.user_id]
    assert (await case.run(apply=True, services_stopped=True))["status"] == "already_applied"


@pytest.mark.anyio
async def test_missing_graph_with_originals_is_never_treated_as_empty_registration():
    workspace = MigrationWorkspace(uuid4(), "absent", "pending")
    resources = SimpleNamespace(
        exists=AsyncMock(return_value=False),
        files=lambda _: SimpleNamespace(empty=AsyncMock(return_value=False)),
    )
    store = SimpleNamespace(processing=AsyncMock(return_value=ProcessingHistory([], [])))
    case = DataMigrations(store, resources, "one", None)
    with pytest.raises(ValueError, match="missing graph database"):
        await case.migrate_workspace(workspace, apply=False)


@pytest.mark.parametrize(
    "first",
    [
        "src.bootstrap.workflows",
        "src.bootstrap.cleanup_extractions",
        "src.bootstrap.worker",
        "src.bootstrap.dispatcher",
    ],
)
def test_process_composition_imports_in_a_fresh_interpreter(first):
    import os
    import subprocess
    import sys

    code = """
import importlib
import sys
importlib.import_module(sys.argv[1])
from src.bootstrap.workflow_registry import registry
from src.bootstrap.worker import execute_processing
assert ('document', 4) in registry.definitions
assert ('audio', 2) in registry.definitions
assert execute_processing.task_name == 'processing.execute'
"""
    subprocess.run(
        [sys.executable, "-c", code, first],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "SENTRY_DSN": ""},
        timeout=15,
    )


@pytest.mark.anyio
async def test_administration_lifespan_does_not_start_public_workspace_resources(monkeypatch):
    import asyncio

    from src.bootstrap import administration, public_api

    admin_close, public_close, reconcile = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(administration, "close_admin_database", admin_close)
    monkeypatch.setattr(public_api, "close_database", public_close)
    monkeypatch.setattr(public_api, "reconcile_active_workspaces", reconcile)
    async with administration.app.router.lifespan_context(administration.app):
        pass
    admin_close.assert_awaited_once()
    public_close.assert_not_awaited()
    reconcile.assert_not_awaited()
    async with public_api.app.router.lifespan_context(public_api.app):
        await asyncio.sleep(0)
    public_close.assert_awaited_once()
    reconcile.assert_awaited_once()
    assert admin_close.await_count == 1
