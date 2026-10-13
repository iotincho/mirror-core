"""Shared lifecycle; algorithm, payload validation and graph representation remain overridable."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel

from src.domain.documents import Document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import (
    ExtractionOutput,
    ExtractorProfile,
    ProviderMetadata,
    content_hash,
)
from src.services.document_store import DocumentStore


class Extractor(ABC):
    name: str

    def __init__(
        self, documents: DocumentStore, artifacts: LayerArtifacts, profile: ExtractorProfile
    ):
        self.documents, self.artifacts, self.profile = documents, artifacts, profile

    @property
    def request_config(self) -> dict[str, str]:
        return {}

    @abstractmethod
    async def produce(self, document: Document) -> tuple[BaseModel, ProviderMetadata | None]: ...

    async def produce_for_run(self, document: Document, run_id: UUID):
        """Allow a layer to checkpoint its own generation steps without changing other layers."""
        return await self.produce(document)

    @abstractmethod
    def validate_payload(self, payload: dict, document: Document) -> BaseModel: ...

    @abstractmethod
    async def write_layer(self, output: ExtractionOutput, payload: BaseModel): ...

    def validate_output(self, output: ExtractionOutput, document: Document) -> BaseModel:
        output.verify()
        if output.extractor != self.name or output.document_id != document.id:
            raise ValueError("extractor_identity_mismatch")
        if output.content_hash != content_hash(document.content):
            raise ValueError("source_changed")
        return self.validate_payload(output.payload, document)

    async def extract(
        self, document: Document, *, dry_run: bool = True, run_id: UUID | None = None
    ) -> ExtractionOutput:
        # Callers supply a stable run ID to resume; fresh calls deliberately accumulate runs.
        run_id = run_id or uuid4()
        current = await self.documents.get(document.id)
        if current.content != document.content:
            raise ValueError("source_changed")
        output = await self.artifacts.get(document.id, run_id)
        if output is None:
            profile, configuration = self.profile, dict(self.request_config)
            payload, provider = await self.produce_for_run(document, run_id)
            if self.profile != profile or self.request_config != configuration:
                raise ValueError("run_configuration_changed")
            current = await self.documents.get(document.id)
            if current.content != document.content:
                raise ValueError("source_changed")
            payload = self.validate_payload(payload.model_dump(mode="json"), document)
            output = ExtractionOutput(
                run_id=run_id,
                document_id=document.id,
                content_hash=content_hash(document.content),
                extractor=self.name,
                profile=profile,
                profile_hash=profile.fingerprint,
                created_at=datetime.now(UTC),
                request_config=configuration,
                provider=provider,
                payload=payload.model_dump(mode="json"),
            )
            await self.artifacts.save(output)
        elif (
            output.profile_hash != self.profile.fingerprint
            or output.request_config != self.request_config
        ):
            raise ValueError("run_configuration_changed")
        self.validate_output(output, current)
        if not dry_run:
            await self.persist(output)
        return output

    async def persist(self, output: ExtractionOutput):
        # Only the bound workspace's durable artifact is writable; arbitrary supplied payloads
        # and artifacts from another workspace cannot be persisted through this interface.
        saved = await self.artifacts.get(output.document_id, output.run_id)
        if saved is None or saved != output:
            raise ValueError("artifact_not_saved_or_changed")
        document = await self.documents.get(output.document_id)
        payload = self.validate_output(output, document)
        await self.write_layer(output, payload)
