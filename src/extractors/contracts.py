"""Serializable execution envelope; payload schemas belong to each extractor."""

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtractorProfile(FrozenModel):
    id: str = Field(min_length=1)
    instructions: str = Field(min_length=1)

    @property
    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))


class ProviderMetadata(FrozenModel):
    provider: str
    model: str
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ExtractionOutput(FrozenModel):
    format: Literal["layer-output/1"] = "layer-output/1"
    run_id: UUID
    document_id: UUID
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    extractor: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    profile: ExtractorProfile
    profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    request_config: dict[str, str]
    provider: ProviderMetadata | None
    payload: dict

    @field_validator("created_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("created_at requires a timezone")
        return value

    def verify(self):
        if self.profile_hash != self.profile.fingerprint:
            raise ValueError("profile_snapshot_mismatch")
