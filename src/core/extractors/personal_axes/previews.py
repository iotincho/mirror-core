"""Preview configuration and locations; independent of HTTP, SQL and paths."""

from dataclasses import dataclass
from uuid import UUID

from src.core.extractors.personal_axes.models import AxisError


@dataclass(frozen=True)
class PreviewConfiguration:
    provider: str
    model: str | None
    max_output_tokens: int
    max_input_chars: int
    max_pending: int
    ttl_hours: int

    def extraction(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "max_output_tokens": self.max_output_tokens,
            "max_input_chars": self.max_input_chars,
        }


@dataclass(frozen=True)
class PreviewLocation:
    owner: UUID
    preview_id: UUID


class SampleSourceUnavailable(AxisError):
    """An unavailable source while selecting a sample, before accepting work."""

    def __init__(self):
        super().__init__("axis_source_unavailable")
