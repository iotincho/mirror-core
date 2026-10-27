"""Audio upload rules independent of storage and transcription."""

from pathlib import Path

SUPPORTED_AUDIO_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class UnsupportedAudioFileError(ValueError):
    pass


class AudioFileTooLargeError(ValueError):
    pass


def validate_audio_upload(
    filename: str | None, media_type: str | None, content: bytes, max_upload_bytes: int
) -> tuple[str, str]:
    if not filename:
        raise UnsupportedAudioFileError("An audio filename is required")
    safe_filename = Path(filename).name
    expected_type = SUPPORTED_AUDIO_TYPES.get(Path(safe_filename).suffix.lower())
    if expected_type is None:
        raise UnsupportedAudioFileError(
            "Unsupported audio type; use m4a, mp3, mp4, mpeg, mpga, wav, or webm"
        )
    if media_type and media_type not in {expected_type, "audio/x-m4a", "audio/x-wav"}:
        raise UnsupportedAudioFileError("Audio MIME type does not match its filename")
    if not content:
        raise UnsupportedAudioFileError("Audio files must not be empty")
    if len(content) > max_upload_bytes:
        raise AudioFileTooLargeError(f"Audio files must be at most {max_upload_bytes} bytes")
    return safe_filename, expected_type
