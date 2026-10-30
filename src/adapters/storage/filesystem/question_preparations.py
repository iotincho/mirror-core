"""Recoverable artifact I/O for daily preparation, without exposing private payloads."""

from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.core.processing.errors import StorageUnavailable


class QuestionPreparationArtifacts(ProcessingArtifacts):
    async def read(self, name, identity):
        try:
            return await super().read(name, identity)
        except OSError:
            raise StorageUnavailable("question_artifact_storage") from None

    async def write(self, name, identity, payload):
        try:
            await super().write(name, identity, payload)
        except OSError:
            raise StorageUnavailable("question_artifact_storage") from None
