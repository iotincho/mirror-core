"""Use cases own stage transitions; the runner owns execution leases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from src.processing.models import ProcessingRecord
from src.processing.repository import LeaseLost, ProcessingRepository

logger = logging.getLogger(__name__)


class WorkflowFailure(Exception):
    """Safe error code and retry decision supplied by the concrete use case."""

    def __init__(self, code: str, retry_delay: float | None = None, retryable: bool | None = None):
        super().__init__(code)
        self.code = code
        self.retry_delay = retry_delay
        self.retryable = retry_delay is not None if retryable is None else retryable


class ResourceBusy(RuntimeError):
    pass


class WorkflowWaiting(Exception):
    """The use case durably handed execution to a child; release the worker."""


@dataclass(frozen=True)
class WorkflowDefinition:
    run: Callable[[ExecutionContext], Awaitable[None]]
    transitions: frozenset[tuple[str, str]]


class WorkflowRegistry:
    def __init__(self):
        self.definitions: dict[tuple[str, int], WorkflowDefinition] = {}

    def register(self, name: str, version: int, definition: WorkflowDefinition):
        key = (name, version)
        if key in self.definitions:
            raise ValueError("workflow_already_registered")
        self.definitions[key] = definition

    def get(self, record: ProcessingRecord) -> WorkflowDefinition:
        try:
            return self.definitions[(record.workflow, record.workflow_version)]
        except KeyError:
            raise WorkflowFailure("workflow_not_registered") from None


@dataclass
class ExecutionContext:
    repository: ProcessingRepository
    record: ProcessingRecord
    definition: WorkflowDefinition

    async def advance(self, stage: str, **checkpoints):
        if (self.record.stage, stage) not in self.definition.transitions:
            raise WorkflowFailure("invalid_workflow_transition")
        await self.repository.advance(self.record, stage, checkpoints)

    async def assert_lease(self):
        async with self.repository.leased(self.record):
            pass


class ExecuteProcessing:
    def __init__(
        self, repository: ProcessingRepository, registry: WorkflowRegistry, max_attempts: int = 4
    ):
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
                if not await self.repository.workspace_active(record.user_id):
                    raise WorkflowFailure("workspace_unavailable")
                definition = self.registry.get(record)
                await definition.run(ExecutionContext(self.repository, record, definition))
                await self.repository.finish(record)
            except WorkflowFailure as error:
                retry = error.retry_delay is not None and record.stage_attempts < self.max_attempts
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
            except SQLAlchemyError:
                # Unexpected errors keep the lease unacknowledged until recovery.
                raise
            except Exception:
                logger.error("Workflow internal error: %s", processing_id)
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
