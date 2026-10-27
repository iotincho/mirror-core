"""Detached accepted definitions and account facts, independent of SQL and HTTP."""

from datetime import datetime
from uuid import UUID

from src.core.extractors.contracts import FrozenModel


class AxisVersion(FrozenModel):
    id: UUID
    number: int
    title: str
    purpose: str
    specification: dict
    specification_hash: str
    created_at: datetime


class AxisDefinition(FrozenModel):
    id: UUID
    enabled: bool
    current_version_id: UUID
    version: AxisVersion


class AxisPage(FrozenModel):
    items: tuple[AxisDefinition, ...]
    next_offset: int | None


class LaboratoryState(FrozenModel):
    active: bool = False
    granted: bool = False
    welcome_dismissed: bool = False
