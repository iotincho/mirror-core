"""The public state shared by snapshots and durable events."""

from datetime import datetime
from uuid import UUID


def processing_projection(record):
    names = (
        "id",
        "workflow",
        "workflow_version",
        "resource_kind",
        "resource_id",
        "document_id",
        "extraction_run_id",
        "parent_processing_id",
        "child_processing_id",
        "status",
        "stage",
        "version",
        "created_at",
        "updated_at",
        "completed_at",
    )
    result = {name: getattr(record, name) for name in names}
    result.update(
        stage_attempt=record.stage_attempts,
        error={
            "code": record.error_code,
            "message": "El procesamiento no pudo avanzar.",
            "retryable": record.retryable,
        }
        if record.error_code
        else None,
        next_attempt_at=record.available_at if record.status == "retrying" else None,
    )
    return {
        key: value.isoformat().replace("+00:00", "Z")
        if isinstance(value, datetime)
        else str(value)
        if isinstance(value, UUID)
        else value
        for key, value in result.items()
    }
