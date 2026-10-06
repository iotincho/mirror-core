from types import SimpleNamespace

import pytest

from src.services.openai_transcription_provider import OpenAITranscriptionProvider


@pytest.mark.anyio
async def test_openai_transcriber_sends_audio_to_the_configured_model(tmp_path) -> None:
    audio_path = tmp_path / "note.webm"
    audio_path.write_bytes(b"audio")
    captured: dict[str, object] = {}

    class FakeTranscriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="Texto transcripto")

    provider = OpenAITranscriptionProvider(
        api_key="unused-in-test",
        model="gpt-transcribe",
        client=SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions())),
    )

    assert await provider.transcribe(audio_path) == "Texto transcripto"
    assert captured["model"] == "gpt-transcribe"
    assert captured["file"] == ("note.webm", b"audio")
