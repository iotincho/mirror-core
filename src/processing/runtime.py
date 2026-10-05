"""Process-local dependencies, shared by workers and the dispatcher."""

from functools import lru_cache

from src.config import get_settings
from src.processing.execution import ExecuteProcessing, WorkflowRegistry
from src.processing.repository import ProcessingRepository
from src.user_management.database import get_session_maker

# Concrete document/audio use cases are registered in stage 4.
registry = WorkflowRegistry()


@lru_cache
def get_repository() -> ProcessingRepository:
    return ProcessingRepository(get_session_maker(), get_settings().processing_lease_seconds)


def get_executor() -> ExecuteProcessing:
    return ExecuteProcessing(get_repository(), registry)
