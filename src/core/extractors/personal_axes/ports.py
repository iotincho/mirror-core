"""Semantic provider/projection ports; storage owns paths, clients and transactions."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from src.core.domain.documents import Document
from src.core.extractors.contracts import ExtractionOutput, ExtractorProfile, ProviderMetadata
from src.core.extractors.personal_axes.definitions import AxisDefinition, AxisPage, LaboratoryState
from src.core.extractors.personal_axes.models import (
    AxisWriteContext,
    Criterion,
    Findings,
    FindingsResponse,
)
from src.core.extractors.personal_axes.read_models import (
    CoverageFacts,
    EvidenceFacts,
    FindingFacts,
    TagFacts,
)


class CriterionGenerator(Protocol):
    async def generate_criterion(self, data: dict) -> tuple[Criterion, ProviderMetadata | None]: ...


class AxisProvider(Protocol):
    async def extract(
        self, document: Document, profile: ExtractorProfile
    ) -> tuple[FindingsResponse, ProviderMetadata | None]: ...
    async def correct(
        self,
        document: Document,
        profile: ExtractorProfile,
        response: FindingsResponse,
        issues: list[dict],
    ) -> tuple[FindingsResponse, ProviderMetadata | None]: ...


class AxisProjection(Protocol):
    async def write(
        self,
        output: ExtractionOutput,
        payload: Findings,
        axis_id: UUID,
        version_id: UUID,
        *,
        context: AxisWriteContext,
    ) -> bool: ...


class AxisWriteContexts(Protocol):
    async def for_reservation(
        self, owner: UUID, processing_id: UUID, axis_id: UUID, version_id: UUID
    ) -> AxisWriteContext: ...


class AxisDefinitions(Protocol):
    async def get(self, owner: UUID, axis_id: UUID) -> AxisDefinition: ...
    async def list(self, owner: UUID, offset: int = 0, limit: int = 50) -> AxisPage: ...
    async def version(self, owner: UUID, axis_id: UUID, version_id: UUID) -> AxisDefinition: ...
    async def set_enabled(self, owner: UUID, axis_id: UUID, enabled: bool) -> AxisDefinition: ...


class LaboratoryAccounts(Protocol):
    async def read(self, owner: UUID) -> LaboratoryState: ...
    async def dismiss_welcome(self, owner: UUID) -> None: ...


class AxisGraphRead(Protocol):
    async def finding(self, finding_id: UUID) -> list[FindingFacts]: ...
    async def findings(
        self, after: str, limit: int, *, document_id=None, tag=None
    ) -> list[FindingFacts]: ...
    async def evidence(self, ids: list[str]) -> list[EvidenceFacts]: ...
    async def tags(self) -> list[TagFacts]: ...
    async def document_ids(self, after: str, limit: int) -> list[str]: ...
    async def coverage(self, document_id=None) -> list[CoverageFacts]: ...


class AxisGraphReads(Protocol):
    def read(
        self, axis_id: UUID, version_id: UUID | None = None
    ) -> AbstractAsyncContextManager[AxisGraphRead]: ...
