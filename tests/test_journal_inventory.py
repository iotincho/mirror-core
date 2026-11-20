"""Confirmed counts use synthetic originals and never require provider calls."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.adapters.access.api.public.routes.journals import build_router
from src.adapters.storage.filesystem.journal_inventory import FileJournalInventory
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.use_cases.journals.query import QueryJournals
from tests.test_journals_application import MemoryJournals


@pytest.fixture
def anyio_backend():
    return "asyncio"


def write(root, kind, identifier, **fields):
    directory = root / kind
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{identifier}.json").write_text(json.dumps(dict(id=str(identifier), **fields)))


@pytest.mark.anyio
async def test_counts_deduplicate_original_audio_derived_text_and_reprocessing(tmp_path):
    owner, other, audio, transcript, run = (uuid4() for _ in range(5))
    reference = dict(schema_version="1", run_id=str(run), run_revision=1, stage_id=str(uuid4()))
    workspace = tmp_path / str(owner)
    write(workspace, "documents", uuid4(), content="synthetic free writing", metadata={})
    write(workspace, "audio-notes", audio, journal_reference=reference,
          document_id=str(transcript), status="failed")
    write(workspace, "documents", transcript, metadata={"journal_reference": json.dumps(reference)})
    write(workspace, "documents", uuid4(), metadata={"audio_note_id": str(audio),
          "journal_reference": json.dumps(reference)})
    write(workspace, "audio-notes", uuid4(), status="queued")
    write(tmp_path / str(other), "documents", uuid4(), metadata={})
    inventory = FileJournalInventory(tmp_path)
    counts = await inventory.counts(owner)
    assert counts.diary == 2
    assert counts.runs == {run: 1}
    assert (await inventory.counts(other)).diary == 1


@pytest.mark.anyio
async def test_malformed_association_or_missing_workspace_never_becomes_zero_diary(tmp_path):
    owner = uuid4()
    inventory = FileJournalInventory(tmp_path)
    with pytest.raises(JournalStorageUnavailable):
        await inventory.counts(owner)
    write(tmp_path / str(owner), "documents", uuid4(), metadata={"journal_reference": "invalid"})
    with pytest.raises(JournalStorageUnavailable):
        await inventory.counts(owner)


@pytest.mark.anyio
async def test_summary_checks_access_before_reading_originals(tmp_path):
    repository = MemoryJournals()
    service = QueryJournals(repository, inventory=FileJournalInventory(tmp_path))
    with pytest.raises(JournalError, match="journal_owner_not_found"):
        await service.summary(uuid4())


@pytest.mark.anyio
async def test_public_summary_is_session_owned_and_storage_errors_are_safe(tmp_path):
    repository = MemoryJournals()
    workspace = tmp_path / str(repository.owner)
    workspace.mkdir()
    service = QueryJournals(repository, inventory=FileJournalInventory(tmp_path))

    class User:
        id = repository.owner

    async def user():
        return User()

    async def queries():
        return service

    async def unused():
        pass

    app = FastAPI()
    app.include_router(build_router(user, queries, unused, unused))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/journals/summary", params={"user_id": str(uuid4())})
        assert response.status_code == 200
        assert response.json()["diary"] == 0
        write(workspace, "documents", uuid4(), metadata={"journal_reference": "invalid"})
        response = await client.get("/journals/summary")
        assert response.status_code == 503
        assert response.json() == {"detail": "journal_storage_unavailable"}


@pytest.mark.anyio
async def test_inventory_rejects_symlinked_originals(tmp_path):
    owner, identifier = uuid4(), uuid4()
    workspace = tmp_path / str(owner)
    (workspace / "documents").mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"id": str(identifier)}))
    (workspace / "documents" / f"{identifier}.json").symlink_to(outside)
    with pytest.raises(JournalStorageUnavailable):
        await FileJournalInventory(tmp_path).counts(owner)


def test_imported_transcripts_share_their_audio_identity_without_metadata_file():
    from src.core.journals.inventory import OriginalEntry, count_originals

    audio = uuid4()
    entries = [OriginalEntry("document", uuid4(), audio_id=audio) for _ in range(2)]
    entries.append(OriginalEntry("document", uuid4()))
    assert count_originals([], entries).diary == 2
