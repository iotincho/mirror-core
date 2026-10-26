"""Semantic provider/projection ports; storage owns paths, clients and transactions."""

from typing import Protocol
from uuid import UUID

from src.core.domain.documents import Document
from src.core.extractors.contracts import ExtractionOutput, ExtractorProfile, ProviderMetadata
from src.core.extractors.personal_axes.models import (
    AxisWriteContext,
    Criterion,
    Findings,
    FindingsResponse,
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
