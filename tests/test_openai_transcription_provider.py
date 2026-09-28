from types import SimpleNamespace

from src.services.openai_transcription_provider import OpenAITranscriptionProvider


def test_openai_transcriber_sends_audio_to_the_configured_model(tmp_path) -> None:
    audio_path = tmp_path / "note.webm"
    audio_path.write_bytes(b"audio")
    captured: dict[str, object] = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="Texto transcripto")

    provider = OpenAITranscriptionProvider(
        api_key="unused-in-test",
        model="gpt-transcribe",
        client=SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions())),
    )

    assert provider.transcribe(audio_path) == "Texto transcripto"
    assert captured["model"] == "gpt-transcribe"
    assert captured["file"].name.endswith("note.webm")
