"""Content-free facts for a single attempt to call an AI provider."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Category = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200)]
TokenCount = Annotated[int, Field(ge=0, le=2**63 - 1)]
Duration = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=6)]


class AiUsageAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    attempt_id: UUID
    user_id: UUID | None
    execution_id: UUID | None = None
    feature: Category
    provider: Category
    requested_model: Identifier


class AiUsageResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    outcome: Literal["succeeded", "failed", "unknown"]
    effective_model: Identifier | None = None
    provider_request_id: Identifier | None = None
    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    total_tokens: TokenCount | None = None
    cached_input_tokens: TokenCount | None = None
    audio_input_tokens: TokenCount | None = None
    duration_seconds: Duration | None = None
