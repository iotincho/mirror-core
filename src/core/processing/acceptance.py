"""Request reservation, original publication and transactional acceptance boundary."""

from typing import Protocol
from uuid import UUID

from src.core.processing.models import ProcessingJob, SubmissionReceipt
from src.core.processing.transactions import ProcessingRequests


class Submissions(Protocol):
    processing: ProcessingRequests

    async def get(self, owner: UUID, operation: str, key: UUID) -> SubmissionReceipt | None: ...

    async def accepted(
        self, owner: UUID, operation: str, key: UUID, request_hash: str
    ) -> SubmissionReceipt | None: ...

    async def reserve(
        self,
        *,
        user_id: UUID,
        operation: str,
        key: UUID,
        request_hash: str,
        resource_kind: str,
        resource_id: UUID | None,
        config: dict,
        manifest: dict,
    ) -> SubmissionReceipt: ...

    async def accept(self, receipt: SubmissionReceipt) -> ProcessingJob: ...

    async def release(self, receipt: SubmissionReceipt) -> None: ...

    async def claim_pending(self) -> list[SubmissionReceipt]: ...

    async def validate_invitation(self, owner: UUID, invitation_id: UUID) -> None: ...
