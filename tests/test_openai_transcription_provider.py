import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx
import pytest
from openai import InternalServerError

from src.adapters.storage.filesystem import audio_transcoding
from src.adapters.storage.filesystem.audio_transcoding import FileTranscriptionSource
from src.bootstrap.audio import build_transcriber as OpenAITranscriptionProvider
from src.bootstrap.failures import failure_for
from src.core.audio.ports import TranscriptionProviderError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def conversion_directory(tmp_path, monkeypatch):
    directory = tmp_path / "conversions"
    directory.mkdir()
    monkeypatch.setattr(
        audio_transcoding,
        "TemporaryDirectory",
        lambda **kwargs: TemporaryDirectory(dir=directory, **kwargs),
    )
    return directory


@pytest.fixture
def webm_path(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for the real audio conversion test")
    # Streaming output intentionally has no declared duration, like browser recordings.
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "0.5",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    path = tmp_path / "note.webm"
    path.write_bytes(result.stdout)
    return path


def provider_for(create):
    return OpenAITranscriptionProvider(
        api_key="unused-in-test",
        model="gpt-transcribe",
        client=SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("suffix", [".mp3", ".m4a", ".wav"])
async def test_openai_transcriber_sends_audio_to_the_configured_model(tmp_path, suffix) -> None:
    audio_path = tmp_path / f"note{suffix}"
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

    assert await provider.transcribe(FileTranscriptionSource(audio_path)) == "Texto transcripto"
    assert captured["model"] == "gpt-transcribe"
    assert captured["file"] == (audio_path.name, b"audio")


@pytest.mark.anyio
@pytest.mark.parametrize("api_fails", [False, True])
async def test_webm_is_sent_as_valid_mp3_and_original_is_preserved(
    webm_path,
    conversion_directory,
    tmp_path,
    api_fails,
):
    original = webm_path.read_bytes()
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        assert list(conversion_directory.iterdir()) == []
        if api_fails:
            raise InternalServerError(
                "Audio file processing failed",
                response=httpx.Response(500, request=httpx.Request("POST", "https://example.test")),
                body=None,
            )
        return SimpleNamespace(text="Texto transcripto")

    provider = provider_for(create)
    if api_fails:
        with pytest.raises(TranscriptionProviderError) as raised:
            await provider.transcribe(FileTranscriptionSource(webm_path))
        failure = failure_for(raised.value, 1, "transcription")
        assert failure.code == "transcription_unavailable"
        assert failure.retry_delay is not None
    else:
        assert await provider.transcribe(FileTranscriptionSource(webm_path)) == "Texto transcripto"

    assert captured["model"] == "gpt-transcribe"
    name, content = captured["file"]
    assert name == "note.mp3"
    converted = tmp_path / name
    converted.write_bytes(content)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(converted),
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout)["streams"] == [
        {"codec_name": "mp3", "sample_rate": "16000", "channels": 1},
    ]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(converted), "-f", "null", "-"],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert webm_path.read_bytes() == original
    assert list(conversion_directory.iterdir()) == []


@pytest.mark.anyio
@pytest.mark.parametrize("reason", ["missing_ffmpeg", "invalid_webm", "oversize_mp3"])
async def test_conversion_failure_does_not_call_api_or_leave_temporary_files(
    tmp_path,
    conversion_directory,
    monkeypatch,
    reason,
):
    path = tmp_path / "note.webm"
    path.write_bytes(b"original")

    async def create(**kwargs):
        pytest.fail("Unconverted audio must not reach OpenAI")

    async def spawn(*args, **kwargs):
        if reason == "missing_ffmpeg":
            raise FileNotFoundError("ffmpeg")
        if reason == "oversize_mp3":
            # A sparse file verifies the size check without allocating the upload in memory.
            with Path(args[-1]).open("wb") as output:
                output.truncate(25_000_001)

        async def wait():
            return process.returncode

        process = SimpleNamespace(returncode=1 if reason == "invalid_webm" else 0, wait=wait)
        return process

    monkeypatch.setattr(audio_transcoding.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(TranscriptionProviderError) as raised:
        await provider_for(create).transcribe(FileTranscriptionSource(path))
    assert isinstance(raised.value.__cause__, audio_transcoding.AudioPreparationError)
    failure = failure_for(raised.value, 1, "transcription")
    if reason == "missing_ffmpeg":
        assert failure.code == "transcription_configuration"
        assert failure.retryable is True
        assert failure.retry_delay is None
    else:
        assert failure.code == "transcription_invalid_response"
        assert failure.retryable is False
    assert path.read_bytes() == b"original"
    assert list(conversion_directory.iterdir()) == []


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interrupted_conversion_stops_process_and_cleans_up(
    tmp_path,
    conversion_directory,
    monkeypatch,
    cancel,
):
    path = tmp_path / "note.webm"
    path.write_bytes(b"original")
    started, stopped = asyncio.Event(), asyncio.Event()

    class Process:
        returncode = None

        async def wait(self):
            started.set()
            await stopped.wait()
            return self.returncode

        def kill(self):
            self.returncode = -9
            stopped.set()

    process = Process()

    async def spawn(*args, **kwargs):
        Path(args[-1]).write_bytes(b"partial MP3")
        return process

    monkeypatch.setattr(audio_transcoding.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        audio_transcoding.transcription_upload(path, timeout=60 if cancel else 0.01)
    )
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert process.returncode == -9
    assert list(conversion_directory.iterdir()) == []
    assert path.read_bytes() == b"original"
