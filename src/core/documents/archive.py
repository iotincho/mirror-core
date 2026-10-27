"""Portable originals and archive validation, independent of storage and jobs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.domain.documents import Document


class ArchivedDocument(Document):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("content", "source")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Document text and source must not be blank")
        return value

    @field_validator("created_at", "authored_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Dates must include timezone")
        return value


class DocumentArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["el-espejo-documents"] = "el-espejo-documents"
    version: Literal[1] = 1
    exported_at: datetime
    documents: list[ArchivedDocument] = Field(max_length=10000)

    @field_validator("documents")
    @classmethod
    def unique_ids(cls, values):
        if len({item.id for item in values}) != len(values):
            raise ValueError("Duplicate document IDs")
        return values


class ArchiveConflict(ValueError):
    pass
