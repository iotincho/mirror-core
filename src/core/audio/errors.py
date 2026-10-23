"""Stable original-audio storage failures."""


class AudioNoteAlreadyExistsError(Exception):
    pass


class AudioNoteNotFoundError(Exception):
    pass


class AudioPreparationError(RuntimeError):
    """Audio could not be prepared for transcription."""


class AudioTranscoderUnavailable(AudioPreparationError):
    """The worker needs its audio conversion dependency installed."""
