"""Workspace-bound immutable layer artifacts, backed by durable processing storage."""

import asyncio
import shutil
from pathlib import Path
from uuid import UUID

from src.extractors.contracts import ExtractionOutput
from src.processing.artifacts import ProcessingArtifacts


class LayerArtifacts:
    def __init__(self, root: Path):
        self.root = Path(root)

    def storage(self, document_id: UUID, run_id: UUID):
        return ProcessingArtifacts(self.root / str(UUID(str(document_id))) / str(UUID(str(run_id))))

    async def get(self, document_id: UUID, run_id: UUID) -> ExtractionOutput | None:
        value = await self.storage(document_id, run_id).read("result", str(run_id))
        if value is None:
            return None
        output = ExtractionOutput.model_validate(value)
        output.verify()
        if output.run_id != run_id or output.document_id != document_id:
            raise ValueError("artifact_identity_mismatch")
        return output

    async def save(self, output: ExtractionOutput):
        output.verify()
        await self.storage(output.document_id, output.run_id).write(
            "result", str(output.run_id), output.model_dump(mode="json")
        )

    async def delete_for_document(self, document_id: UUID):
        directory = self.root / str(UUID(str(document_id)))
        if directory.exists():
            await asyncio.to_thread(shutil.rmtree, directory)
