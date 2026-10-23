"""Compatibility imports for the original-audio port and filesystem adapter."""

from src.adapters.storage.filesystem.audio_notes import FileAudioNoteStore as FileAudioNoteStore
from src.core.audio.errors import AudioNoteAlreadyExistsError as AudioNoteAlreadyExistsError
from src.core.audio.errors import AudioNoteNotFoundError as AudioNoteNotFoundError
from src.core.audio.ports import AudioNoteStore as AudioNoteStore
