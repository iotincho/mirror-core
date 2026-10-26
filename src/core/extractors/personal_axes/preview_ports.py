"""Semantic preview storage and atomic scheduling contracts."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.extractors.artifacts import LayerArtifacts
from src.core.extractors.personal_axes.definitions import AxisDefinition
from src.core.extractors.personal_axes.models import AxisSpecification, PreviewRequest
from src.core.extractors.personal_axes.ports import AxisDefinitions
from src.core.extractors.personal_axes.previews import PreviewLocation
from src.core.processing.models import ProcessingJob, SubmissionReceipt


class AxisApprovals(AxisDefinitions, Protocol):
    async def approved(
        self, owner: UUID, preview_id: UUID, revision_hash: str
    ) -> AxisDefinition | None: ...
    async def accept(
        self,
        owner: UUID,
        preview_id: UUID,
        request: PreviewRequest,
        specification: AxisSpecification,
        expires_at: datetime,
    ) -> AxisDefinition: ...


class PreviewArtifacts(Protocol):
    id: UUID
    layers: LayerArtifacts

    def run_id(self, document_id: UUID | str) -> UUID: ...
    async def read(self, name: str) -> dict | None: ...
    async def write(self, name: str, value: dict) -> None: ...
    async def delete(self) -> None: ...


class PreviewFiles(Protocol):
    def for_preview(self, preview_id: UUID) -> PreviewArtifacts: ...


class PreviewReservation(Protocol):
    now: datetime

    async def enqueue(
        self, preview_id: UUID, key: UUID, request_hash: str, sources: dict, expires_at: datetime
    ) -> None: ...


class PreviewRetry(Protocol):
    receipt: SubmissionReceipt | None

    async def record(self, job: ProcessingJob, key: UUID) -> None: ...


class PreviewTransactions(Protocol):
    async def get(self, owner: UUID, preview_id: UUID) -> ProcessingJob | None: ...
    async def receipt(self, owner: UUID, operation: str, key: UUID) -> SubmissionReceipt | None: ...
    def guard(self, owner: UUID, preview_id: UUID) -> AbstractAsyncContextManager[bool]: ...
    def sources(
        self, owner: UUID, ids: list[UUID], *, shared=False
    ) -> AbstractAsyncContextManager[bool]: ...
    def reservation(
        self, owner: UUID, max_pending: int
    ) -> AbstractAsyncContextManager[PreviewReservation]: ...
    def retrying(self, owner: UUID, key: UUID) -> AbstractAsyncContextManager[PreviewRetry]: ...


class PreviewMaintenance(PreviewTransactions, Protocol):
    async def expired(self, limit: int) -> list[ProcessingJob]: ...
    async def remove(self, owner: UUID, preview_id: UUID) -> None: ...


class PreviewRoots(Protocol):
    async def candidates(self, limit: int) -> list[PreviewLocation]: ...
    def for_owner(self, owner: UUID) -> PreviewFiles: ...
