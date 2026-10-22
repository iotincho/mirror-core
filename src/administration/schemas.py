from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    is_active: bool
    laboratory_enabled: bool
    laboratory_global_enabled: bool
    created_at: datetime | None
    last_activity_at: datetime | None
    notes_count: int | None


class UserList(BaseModel):
    items: list[UserRead]
    total: int


class LaboratoryAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    laboratory_enabled: StrictBool


class Sources(BaseModel):
    writing: int | None
    audio: int | None
    imported: int | None


class ProcessingCounts(BaseModel):
    completed: int
    failed: int
    pending: int
    running: int


class Coverage(BaseModel):
    activity_since: datetime | None
    documents_complete: bool
    inventory_synced_at: datetime | None
    notes_complete: bool


class DashboardSummary(BaseModel):
    period_days: int
    timezone: str = "America/Argentina/Buenos_Aires"
    updated_at: datetime
    users_total: int
    users_active: int
    users_accessed: int | None
    users_wrote: int | None
    notes_total: int | None
    notes_created: int | None
    notes_by_source: Sources
    processing: ProcessingCounts
    coverage: Coverage


class ActivityPoint(BaseModel):
    date: date
    accessed: int | None
    wrote: int | None


class ActivitySeries(BaseModel):
    items: list[ActivityPoint]
