"""Durable local storage for auditable reflection runs."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from src.embeddings.contracts import SimilarClaim
from src.reflection.contracts import ClaimRelation, ReflectionResult
from src.services.structured_extractor import TokenUsage


class ReflectionRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    question: str
    profile_name: str
    prompt_version: str
    provider: str
    model: str
    status: Literal["completed", "failed"]
    created_at: datetime
    candidates: list[SimilarClaim]
    relations: list[ClaimRelation]
    result: ReflectionResult | None = None
    response_id: str | None = None
    usage: TokenUsage | None = None
    error: str | None = None


def new_reflection_run(**values: object) -> ReflectionRun:
    return ReflectionRun(id=uuid4(), created_at=datetime.now(UTC), **values)


class ReflectionStore(Protocol):
    async def save(self, run: ReflectionRun) -> None: ...


class FileReflectionStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def save(self, run: ReflectionRun) -> None:
        return await asyncio.to_thread(self._save, run)

    def _save(self, run: ReflectionRun) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        destination = self._directory / f"{run.id}.json"
        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
