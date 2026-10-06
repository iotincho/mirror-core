import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_audio_note_store
from src.main import app
from src.services.audio_note_store import FileAudioNoteStore
from src.use_cases.create_audio_note import CreateAudioNote


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_original_audio_remains_readable_without_legacy_background_processing(tmp_path):
    store = FileAudioNoteStore(tmp_path)
    note = await CreateAudioNote(store, 1024).execute("note.webm", "audio/webm", b"audio", None)
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    app.dependency_overrides[get_audio_note_store] = lambda: store
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.post("/audio-notes")).status_code == 410
            assert (await client.post(f"/audio-notes/{note.id}/documents")).status_code == 410
            response = await client.get(f"/audio-notes/{note.id}")
            assert response.status_code == 200
            assert response.json()["id"] == str(note.id)
        assert store.audio_path(note).read_bytes() == b"audio"
    finally:
        app.dependency_overrides.clear()
