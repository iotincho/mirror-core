"""Transport-only representation of a historical capture reference."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JournalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    schema_version: Literal["1"] = "1"
    run_id: UUID
    stage_id: UUID
    run_revision: int = Field(strict=True, ge=1)
