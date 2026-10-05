from types import SimpleNamespace

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import (
    get_audio_note_store,
    get_create_audio_note,
    get_transcribe_audio_note,
)
from src.main import app
from src.services.audio_note_store import FileAudioNoteStore
from src.use_cases.transcribe_audio_note import CreateAudioNote, TranscribeAudioNote


class FakeTranscriber:
    provider_name = "fake"
    model_name = "fake-transcriber"

    async def transcribe(self, audio_path) -> str:
        assert audio_path.read_bytes() == b"audio-bytes"
        return "Una reflexión grabada."


class FakeDocumentProcessor:
    def __init__(self) -> None:
        self.documents = []

    async def execute(self, document):
        self.documents.append(document)
        return SimpleNamespace(document=SimpleNamespace(id=document.id))


@pytest.fixture
def audio_store(tmp_path) -> FileAudioNoteStore:
    return FileAudioNoteStore(tmp_path / "audio-notes")


@pytest.mark.anyio
async def test_audio_note_is_persisted_and_transcribed_in_background(audio_store) -> None:
    document_processor = FakeDocumentProcessor()

    async def override_create() -> CreateAudioNote:
        return CreateAudioNote(audio_store, max_upload_bytes=1024)

    async def override_transcribe() -> TranscribeAudioNote:
        return TranscribeAudioNote(audio_store, FakeTranscriber(), document_processor)

    app.dependency_overrides[get_create_audio_note] = override_create
    app.dependency_overrides[get_transcribe_audio_note] = override_transcribe
    app.dependency_overrides[get_audio_note_store] = lambda: audio_store
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio-notes",
                data={"authored_at": "2026-09-28T10:30:00-03:00"},
                files={"file": ("nota.webm", b"audio-bytes", "audio/webm")},
            )
            assert response.status_code == 202, response.text
            created = response.json()
            fetched = await client.get(f"/audio-notes/{created['id']}")
    finally:
        app.dependency_overrides.clear()

    assert created["status"] == "queued"
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["status"] == "completed"
    assert fetched.json()["transcript"] == "Una reflexión grabada."
    assert fetched.json()["transcription_provider"] == "fake"
    assert fetched.json()["document_id"] == created["id"]
    assert str(document_processor.documents[0].id) == created["id"]
    assert document_processor.documents[0].source == "pwa_audio"
    assert document_processor.documents[0].content == "Una reflexión grabada."
    assert len(list((audio_store._directory).glob("*.webm"))) == 1


@pytest.mark.anyio
async def test_audio_note_rejects_an_unsupported_file_type(audio_store) -> None:
    document_processor = FakeDocumentProcessor()

    async def override_create() -> CreateAudioNote:
        return CreateAudioNote(audio_store, max_upload_bytes=1024)

    async def override_transcribe() -> TranscribeAudioNote:
        return TranscribeAudioNote(audio_store, FakeTranscriber(), document_processor)

    app.dependency_overrides[get_create_audio_note] = override_create
    app.dependency_overrides[get_transcribe_audio_note] = override_transcribe
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio-notes",
                files={"file": ("nota.ogg", b"audio-bytes", "audio/ogg")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 415


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
