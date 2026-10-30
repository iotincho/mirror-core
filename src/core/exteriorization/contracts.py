"""Pure engine inputs and immutable outputs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Trigger(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Literal["generic", "personalized"] = "generic"
    candidate_id: str
    category: str
    question: str
    engine_version: str = "generic-v1"
    catalog_version: str = "1"


@dataclass(frozen=True)
class EngineContext:
    now: datetime
    timezone: str
    # Most recent first; only scheduled invitations belong here.
    history: tuple[Trigger, ...] = ()
