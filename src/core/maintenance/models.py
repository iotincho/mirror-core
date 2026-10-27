"""Detached operational migration facts; IDs and backup records retain their format."""

from dataclasses import dataclass
from uuid import UUID

from src.core.processing.models import ProcessingJob

MIGRATION_ID = "20261006-retire-exploratory-extraction"


@dataclass(frozen=True)
class MigrationWorkspace:
    user_id: UUID
    database_name: str
    status: str


@dataclass(frozen=True)
class MigrationState:
    status: str
    details: dict


@dataclass(frozen=True)
class ProcessingHistory:
    records: list[ProcessingJob]
    rows: list[dict]
