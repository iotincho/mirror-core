"""Personal-axis payloads; execution envelopes belong to extractors.contracts."""

import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from src.extractors.contracts import ExtractorProfile, FrozenModel, digest


def label_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class AxisError(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


class Criterion(FrozenModel):
    instructions: str = Field(min_length=1, max_length=16000)


class AxisSpecification(FrozenModel):
    profile: ExtractorProfile
    provider: str = "openai"
    model: str = Field(min_length=1)
    max_output_tokens: int = Field(default=6000, ge=256, le=32000)
    max_input_chars: int = Field(default=100000, ge=1000, le=1000000)
    output_contract_version: Literal["personal-findings/1"] = "personal-findings/1"
    validation_policy_version: Literal["personal-evidence/1"] = "personal-evidence/1"

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode="json"))


class Evidence(FrozenModel):
    quote: str = Field(max_length=20000)


class Finding(FrozenModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12000)
    evidence: list[Evidence] = Field(max_length=30)
    tags: list[str] = Field(max_length=20)


class FindingsResponse(FrozenModel):
    findings: list[Finding] = Field(max_length=100)


class Findings(FindingsResponse):
    warnings: list[str] = Field(default_factory=list)


class PreviewRequest(FrozenModel):
    draft_id: UUID
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=8000)
    document_ids: list[UUID] = Field(min_length=5, max_length=5)
    mode: Literal["generate", "refine", "repeat"] = "generate"
    previous_preview_id: UUID | None = None
    change_sample: bool = False
    adjustments: list[str] = Field(default_factory=list, max_length=20)
    axis_id: UUID | None = None
    base_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_request(self):
        if not self.title.strip() or not self.purpose.strip():
            raise ValueError("axis_description_empty")
        if len(set(self.document_ids)) != 5:
            raise ValueError("axis_sample_requires_five_distinct_notes")
        if any(not value.strip() or len(value) > 4000 for value in self.adjustments):
            raise ValueError("axis_adjustment_invalid")
        if (self.mode != "generate") != (self.previous_preview_id is not None):
            raise ValueError("axis_previous_preview_required")
        if (self.axis_id is None) != (self.base_version_id is None):
            raise ValueError("axis_base_version_required")
        return self

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode="json"))


class AcceptPreview(FrozenModel):
    revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
