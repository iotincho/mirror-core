"""Bounded, lock-aware deletion of temporary jobs and orphaned preview artifacts."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select

from src.adapters.storage.postgres.models import (
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.extractors.personal_axes.preview_store import PreviewStore

_orphan_cursors = {}


async def expire_axis_previews(repository, settings):
    async with repository.sessions() as session:
        records = list(
            (
                await session.scalars(
                    select(ProcessingRecord)
                    .where(
                        ProcessingRecord.workflow == "axis_preview",
                        or_(
                            ProcessingRecord.expires_at <= func.clock_timestamp(),
                            ProcessingRecord.resource_deleted.is_(True),
                        ),
                    )
                    .order_by(ProcessingRecord.created_at)
                    .limit(50)
                )
            ).all()
        )
    for record in records:
        async with repository.lock_resource(record.user_id, record.resource_id) as locked:
            if not locked:
                continue
            store = PreviewStore(settings.workspaces_path / str(record.user_id), record.resource_id)
            await store.delete()
            async with repository.sessions.begin() as session:
                await session.execute(
                    delete(ProcessingReceipt).where(ProcessingReceipt.processing_id == record.id)
                )
                await session.execute(
                    delete(ProcessingOutbox).where(ProcessingOutbox.processing_id == record.id)
                )
                await session.execute(
                    delete(ProcessingRecord).where(ProcessingRecord.id == record.id)
                )
    # A transaction interrupted after its immutable input write can leave no SQL row.
    # Inspect a bounded rotation of workspace directories (mtime is not an authority).
    root = settings.workspaces_path
    if not root.exists():
        return
    checked = 0
    cursor = _orphan_cursors.get(str(root), "")
    for directory in sorted(root.glob("*/laboratory/previews/*")):
        if str(directory) <= cursor:
            continue
        if checked >= 200:
            break
        checked += 1
        _orphan_cursors[str(root)] = str(directory)
        try:
            owner, preview_id = UUID(directory.parents[2].name), UUID(directory.name)
        except ValueError:
            continue
        store = PreviewStore(root / str(owner), preview_id)
        value = await store.read("input")
        if value is None or datetime.fromisoformat(value["expires_at"]) > datetime.now(UTC):
            continue
        async with repository.lock_resource(owner, preview_id) as locked:
            if locked and await repository.get(preview_id, owner) is None:
                await store.delete()
    if checked < 200:
        _orphan_cursors.pop(str(root), None)
