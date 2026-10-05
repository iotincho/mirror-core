"""Durable, local storage for extraction runs before graph persistence exists."""

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.contracts import ExtractionResult
from src.services.structured_extractor import TokenUsage


class ExtractionRun(BaseModel):
    """An auditable extraction attempt, completed or failed."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    document_id: UUID
    profile_name: str
    schema_version: str
    prompt_version: str
    provider: str
    model: str
    status: Literal["completed", "failed"]
    created_at: datetime
    result: ExtractionResult | None = None
    response_id: str | None = None
    usage: TokenUsage | None = None
    error: str | None = None
    origin: Literal["extraction", "constellation"] = "extraction"
    parent_run_id: UUID | None = None
    item_graph_ids: dict[str, str] = Field(default_factory=dict)
    reused_item_keys: list[str] = Field(default_factory=list)


def new_extraction_run(**values: object) -> ExtractionRun:
    """Set run identity and timestamp consistently for every attempt."""
    return ExtractionRun(id=uuid4(), created_at=datetime.now(UTC), **values)


class ExtractionStore(Protocol):
    async def delete_for_document(self, document_id: object) -> None: ...

    async def save(self, run: ExtractionRun) -> None:
        """Persist one immutable extraction attempt."""

    async def get(self, document_id: UUID, run_id: UUID) -> ExtractionRun: ...

    async def list_for_document(self, document_id: UUID) -> list[ExtractionRun]: ...


class FileExtractionStore:
    """Store runs under their source-document ID for local inspection."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def delete_for_document(self, document_id: object) -> None:
        return await asyncio.to_thread(self._delete_for_document, document_id)

    async def save(self, run: ExtractionRun) -> None:
        return await asyncio.to_thread(self._save, run)

    async def get(self, document_id: UUID, run_id: UUID) -> ExtractionRun:
        return await asyncio.to_thread(self._get, document_id, run_id)

    async def list_for_document(self, document_id: UUID) -> list[ExtractionRun]:
        return await asyncio.to_thread(self._list_for_document, document_id)

    def _delete_for_document(self, document_id: object) -> None:
        directory = self._directory / str(document_id)
        if directory.exists():
            shutil.rmtree(directory)

    def _save(self, run: ExtractionRun) -> None:
        directory = self._directory / str(run.document_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{run.id}.json"
        temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    def _get(self, document_id: UUID, run_id: UUID) -> ExtractionRun:
        """Load only a run under the authenticated workspace's document directory."""
        source = self._directory / str(document_id) / f"{run_id}.json"
        if not source.is_file():
            raise FileNotFoundError("Extraction run not found")
        run = ExtractionRun.model_validate_json(source.read_text(encoding="utf-8"))
        if run.document_id != document_id or run.id != run_id:
            raise ValueError("Extraction run identity does not match its path")
        return run

    def _list_for_document(self, document_id: UUID) -> list[ExtractionRun]:
        """Read immutable runs only inside this workspace's document directory."""
        runs = [
            self._get(document_id, UUID(path.stem))
            for path in (self._directory / str(document_id)).glob("*.json")
        ]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)
