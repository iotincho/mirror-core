"""Lease-owned execution, heartbeat and safe workflow outcomes through storage ports."""

import asyncio
import logging
from uuid import UUID, uuid4

from src.core.processing.errors import (
    LeaseLost,
    ResourceBusy,
    StorageUnavailable,
    WorkflowFailure,
    WorkflowWaiting,
)
from src.core.processing.ports import ExecutionStore
from src.core.processing.workflows import WorkflowRegistry
from src.use_cases.processing.context import ExecutionContext

logger = logging.getLogger(__name__)


class ExecuteProcessing:
    def __init__(
        self,
        repository: ExecutionStore,
        registry: WorkflowRegistry,
        max_attempts: int = 4,
        *,
        report_issue=lambda *args, **kwargs: None,
    ):
        self.report_issue = report_issue
        self.repository = repository
        self.registry = registry
        self.max_attempts = max_attempts

    async def __call__(self, processing_id: UUID, generation: int):
        async with self.repository.resource_guard(processing_id) as locked:
            if not locked:
                raise ResourceBusy(str(processing_id))
            record = await self.repository.acquire(processing_id, generation, str(uuid4()))
            if record is None:
                return  # Duplicate, obsolete generation, or already durably resolved.
            current_task = asyncio.current_task()

            async def renew():
                while True:
                    await asyncio.sleep(self.repository.lease_seconds / 3)
                    try:
                        await self.repository.heartbeat(record)
                    except Exception:
                        current_task.cancel()
                        raise

            heartbeat = asyncio.create_task(renew())
            try:
                if record.resource_deleted:
                    raise WorkflowFailure("resource_deleted")
                definition = self.registry.get(record)
                if definition.requires_workspace and not await self.repository.workspace_active(
                    record.user_id
                ):
                    raise WorkflowFailure("workspace_unavailable")
                await definition.run(ExecutionContext(self.repository, record, definition))
                await self.repository.finish(record)
            except WorkflowFailure as error:
                retry = error.retry_delay is not None and record.stage_attempts < self.max_attempts
                self.report_issue(
                    "workflow_failure",
                    error,
                    processing_id=processing_id,
                    resource_id=record.resource_id,
                    workflow=record.workflow,
                    stage=record.stage,
                    attempt=record.stage_attempts,
                    error_code=error.code,
                    retry=retry,
                )
                logger.log(
                    logging.WARNING if retry else logging.ERROR,
                    "Workflow failure: processing_id=%s document_id=%s resource_id=%s "
                    "workflow=%s extractor=%s stage=%s attempt=%s error_code=%s retry=%s",
                    processing_id,
                    record.document_id,
                    record.resource_id,
                    record.workflow,
                    record.extractor_name,
                    record.stage,
                    record.stage_attempts,
                    error.code,
                    retry,
                    exc_info=True,
                )
                await self.repository.finish(
                    record,
                    status="retrying" if retry else "failed",
                    error_code=error.code,
                    retry_delay=error.retry_delay if retry else None,
                    retryable=error.retryable,
                )
            except WorkflowWaiting:
                return
            except LeaseLost:
                # Reconciliation owns the replacement generation; no stale mutation.
                return
            except StorageUnavailable as error:
                self.report_issue(
                    "workflow_database_error",
                    error,
                    processing_id=processing_id,
                    workflow=record.workflow,
                    stage=record.stage,
                )
                # Unexpected errors keep the lease unacknowledged until recovery.
                logger.exception(
                    "Workflow database error: processing_id=%s document_id=%s "
                    "workflow=%s extractor=%s stage=%s",
                    processing_id,
                    record.document_id,
                    record.workflow,
                    record.extractor_name,
                    record.stage,
                )
                raise
            except Exception as error:
                self.report_issue(
                    "workflow_internal_error",
                    error,
                    processing_id=processing_id,
                    workflow=record.workflow,
                    stage=record.stage,
                )
                logger.exception(
                    "Workflow internal error: processing_id=%s document_id=%s "
                    "workflow=%s extractor=%s stage=%s",
                    processing_id,
                    record.document_id,
                    record.workflow,
                    record.extractor_name,
                    record.stage,
                )
                await self.repository.finish(
                    record,
                    status="failed",
                    error_code="workflow_internal_error",
                )
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
