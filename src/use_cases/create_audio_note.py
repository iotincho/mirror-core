"""Compatibility imports for original audio registration and validation rules."""

from src.core.audio.uploads import SUPPORTED_AUDIO_TYPES as SUPPORTED_AUDIO_TYPES
from src.core.audio.uploads import AudioFileTooLargeError as AudioFileTooLargeError
from src.core.audio.uploads import UnsupportedAudioFileError as UnsupportedAudioFileError
from src.core.audio.uploads import validate_audio_upload as validate_audio_upload
from src.use_cases.audio.create_audio_note import CreateAudioNote as CreateAudioNote
