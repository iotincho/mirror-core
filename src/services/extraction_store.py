"""Durable, local storage for extraction runs before graph persistence exists."""

import json
from datetime import UTC, datetime
from pathlib import Path
import shutil
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

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


def new_extraction_run(**values: object) -> ExtractionRun:
    """Set run identity and timestamp consistently for every attempt."""
    return ExtractionRun(id=uuid4(), created_at=datetime.now(UTC), **values)


class ExtractionStore(Protocol):
    def delete_for_document(self, document_id: object) -> None: ...

    def save(self, run: ExtractionRun) -> None:
        """Persist one immutable extraction attempt."""


class FileExtractionStore:
    """Store runs under their source-document ID for local inspection."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def delete_for_document(self, document_id: object) -> None:
        directory = self._directory / str(document_id)
        if directory.exists():
            shutil.rmtree(directory)

    def save(self, run: ExtractionRun) -> None:
        directory = self._directory / str(run.document_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{run.id}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    def get(self, document_id: UUID, run_id: UUID) -> ExtractionRun:
        """Load only a run under the authenticated workspace's document directory."""
        source = self._directory / str(document_id) / f"{run_id}.json"
        if not source.is_file():
            raise FileNotFoundError("Extraction run not found")
        run = ExtractionRun.model_validate_json(source.read_text(encoding="utf-8"))
        if run.document_id != document_id or run.id != run_id:
            raise ValueError("Extraction run identity does not match its path")
        return run
