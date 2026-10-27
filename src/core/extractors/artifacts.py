"""Durable artifact ports; paths and publication belong to storage adapters."""

from typing import Protocol
from uuid import UUID

from src.core.extractors.contracts import ExtractionOutput


class ArtifactCorrupted(ValueError):
    pass


class CheckpointArtifacts(Protocol):
    async def read(self, name: str, identity: str) -> dict | None: ...

    async def write(self, name: str, identity: str, payload: dict) -> None: ...


class LayerArtifacts(Protocol):
    def storage(self, document_id: UUID, run_id: UUID) -> CheckpointArtifacts: ...

    async def get(self, document_id: UUID, run_id: UUID) -> ExtractionOutput | None: ...

    async def save(self, output: ExtractionOutput) -> None: ...

    async def delete_for_document(self, document_id: UUID) -> None: ...
