"""Prepare transient provider uploads while retaining the original audio."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory


class AudioPreparationError(RuntimeError):
    """Audio could not be prepared for transcription."""


class AudioTranscoderUnavailable(AudioPreparationError):
    """The worker needs its audio conversion dependency installed."""


async def transcription_upload(audio_path: Path, *, timeout: float) -> tuple[str, bytes]:
    if audio_path.suffix.lower() != ".webm":
        return audio_path.name, await asyncio.to_thread(audio_path.read_bytes)

    with TemporaryDirectory(prefix="mirror-transcription-") as directory:
        output = Path(directory) / "audio.mp3"
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(audio_path.resolve()),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "64k",
                str(output),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise AudioTranscoderUnavailable("WebM transcription requires ffmpeg") from None

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

        if process.returncode != 0 or not output.is_file():
            raise AudioPreparationError("WebM to MP3 conversion failed")
        if not 0 < output.stat().st_size <= 25_000_000:
            raise AudioPreparationError("Converted MP3 must be nonempty and at most 25 MB")
        return audio_path.with_suffix(".mp3").name, await asyncio.to_thread(output.read_bytes)
