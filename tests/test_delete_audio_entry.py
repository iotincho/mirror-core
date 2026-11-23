from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.adapters.storage.filesystem.audio_notes import FileAudioNoteStore
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.core.audio.errors import AudioNoteNotFoundError
from src.core.domain.audio_notes import new_audio_note
from src.core.domain.documents import NewDocument, build_document
from src.core.processing.submissions import SubmissionConflict
from src.use_cases.audio.delete_audio_entry import DeleteAudioEntry
from src.use_cases.documents.delete_document import DeleteDocument


@pytest.mark.anyio
async def test_audio_delete_cleans_legacy_documents_and_can_resume_by_upload_key(tmp_path):
    audio = FileAudioNoteStore(tmp_path / "audio")
    documents = FileDocumentStore(tmp_path / "documents")
    note = new_audio_note("voice.webm", "audio/webm", 4, None)
    original = build_document(NewDocument(content="Una entrada sintética"))
    alias = build_document(
        NewDocument(content="Transcripción sintética", metadata={"audio_note_id": str(note.id)})
    )
    other = build_document(NewDocument(content="Otra entrada"))
    note = note.model_copy(update={"document_id": original.id, "transcript": "Transcripción"})
    audio.audio_path(note).parent.mkdir()
    audio.audio_path(note).write_bytes(b"test")
    (audio.audio_path(note).parent / f"{note.id}.json").write_text(
        note.model_dump_json(), encoding="utf-8"
    )
    originals = tmp_path / "documents"
    originals.mkdir()
    for document in (original, alias, other):
        (originals / f"{document.id}.json").write_text(document.model_dump_json(), encoding="utf-8")
        (tmp_path / "layers" / str(document.id)).mkdir(parents=True)

    job_id, owner, key = uuid4(), uuid4(), uuid4()
    ids = {note.id, original.id, alias.id}
    artifacts = ProcessingArtifacts(tmp_path / "processing" / str(job_id))
    artifacts.directory.mkdir(parents=True)
    (artifacts.directory / "transcript.json").write_text(
        '{"text":"Transcripción"}', encoding="utf-8"
    )
    marked, graphs = set(), set()

    class Graph:
        async def delete_document(self, document_id):
            if not graphs and fail_graph:
                raise OSError("temporary failure")
            graphs.add(document_id)

    class Processing:
        @asynccontextmanager
        async def lock_resources(self, user_id, resources):
            assert user_id == owner
            assert set(resources) == ids
            yield True

        async def assert_inactive(self, user_id, resource_id):
            assert user_id == owner
            if active and resource_id == alias.id:
                raise ValueError("processing_active")

        async def mark_deleted(self, user_id, resource_id):
            assert user_id == owner
            marked.add(resource_id)

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def receipt(self, user_id, operation, upload_key):
            assert (user_id, operation, upload_key) == (owner, "upload_audio", key)
            return SimpleNamespace(accepted_at=datetime.now(UTC), resource_id=note.id)

        async def jobs_for_resources(self, user_id, resources):
            assert user_id == owner
            assert set(resources) == ids
            return [SimpleNamespace(id=job_id)]

    async def delete_artifacts(identifier):
        assert identifier == job_id
        await artifacts.delete()

    delete = DeleteAudioEntry(
        owner,
        audio,
        documents,
        DeleteDocument(documents, Graph(), layer_artifacts=LayerArtifacts(tmp_path / "layers")),
        Processing(),
        delete_artifacts,
    )
    active, fail_graph = True, True
    with pytest.raises(SubmissionConflict, match="processing_active"):
        await delete.execute(note.id)
    assert not marked
    assert artifacts.directory.exists()

    active = False
    with pytest.raises(OSError, match="temporary"):
        await delete.execute(note.id)
    assert marked == ids
    assert audio.audio_path(note).is_file()

    fail_graph = False
    await delete.execute(key, by_upload_key=True)
    assert not audio.audio_path(note).exists()
    assert not artifacts.directory.exists()
    assert graphs == {str(original.id), str(alias.id)}
    assert [item.id for item in await documents.list()] == [other.id]
    assert list((tmp_path / "layers").iterdir()) == [tmp_path / "layers" / str(other.id)]
    with pytest.raises(AudioNoteNotFoundError):
        await audio.get(note.id)
    with pytest.raises(AudioNoteNotFoundError):
        await delete.execute(key, by_upload_key=True)
