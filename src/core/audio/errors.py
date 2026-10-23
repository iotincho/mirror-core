"""Stable original-audio storage failures."""


class AudioNoteAlreadyExistsError(Exception):
    pass


class AudioNoteNotFoundError(Exception):
    pass
