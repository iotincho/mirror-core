"""Reconcile originals into a SQL metadata inventory, independently of the admin API.

Run once for backfill, or with --interval 30 for LAN development. Checkpoints commit
per account. A failed read invalidates coverage without deleting the previous index.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.accounts import User
from src.administration.config import get_admin_settings
from src.administration.database import close_admin_database, get_admin_sessions
from src.administration.models import DocumentMetric, InventoryState
from src.processing.models import ProcessingReceipt, ProcessingRecord

LOCK_ID = 814021069


class OriginalMetadata(BaseModel):
    id: UUID
    created_at: datetime
    source: str = Field(max_length=100)

    @field_validator("created_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("original date must include timezone")
        return value


def read_metadata(directory: Path):
    if directory.is_symlink():
        raise ValueError("symlink_directory")
    if not directory.exists():
        return None
    result = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("invalid_original")
        data = OriginalMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        if path.stem != str(data.id):
            raise ValueError("original_identity_mismatch")
        result.append(data)
    return result


def classify(source):
    if source in {"pwa_audio", "audio"}:
        return "audio"
    if source == "file_upload":
        return "imported"
    if source in {"pwa_note", "manual", "api", "note", "pwa"}:
        return "writing"
    return None


class SyncInventory:
    def __init__(self, sessions, root):
        self.sessions, self.root = sessions, Path(root)

    async def invalidate(self, user_id):
        async with self.sessions.begin() as session:
            statement = insert(InventoryState).values(user_id=user_id, complete=False)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[InventoryState.user_id], set_={"complete": False}
                )
            )

    async def account(self, user_id):
        stamp = datetime.now(UTC)
        async with self.sessions() as session:
            receipts = (
                await session.execute(
                    select(
                        ProcessingReceipt.resource_id,
                        ProcessingReceipt.operation,
                        ProcessingReceipt.accepted_at,
                        ProcessingRecord.resource_deleted,
                    )
                    .outerjoin(
                        ProcessingRecord, ProcessingRecord.id == ProcessingReceipt.processing_id
                    )
                    .where(
                        ProcessingReceipt.user_id == user_id,
                        ProcessingReceipt.accepted_at.is_not(None),
                        ProcessingReceipt.is_original.is_(True),
                        ProcessingReceipt.operation.in_(
                            ["upload_document", "upload_audio", "import_document"]
                        ),
                    )
                    .order_by(ProcessingReceipt.accepted_at)
                )
            ).all()
            previous = set(
                (
                    await session.scalars(
                        select(DocumentMetric.document_id).where(DocumentMetric.user_id == user_id)
                    )
                ).all()
            )
        directory = self.root / str(user_id) / "documents"
        if directory.parent.is_symlink():
            raise ValueError("symlink_workspace")
        originals = await asyncio.to_thread(read_metadata, directory)
        by_id = {}
        for receipt in receipts:
            by_id.setdefault(receipt.resource_id, receipt)
        if originals is None:
            # No directory is normal for a newly registered empty account only.
            if previous or receipts:
                raise ValueError("workspace_directory_missing")
            originals = []
        seen = {item.id for item in originals}
        missing = [
            r
            for r in receipts
            if r.operation != "upload_audio"
            and r.resource_id not in seen
            and r.resource_id not in previous
        ]
        if any(not receipt.resource_deleted for receipt in missing):
            raise ValueError("accepted_original_missing")
        async with self.sessions.begin() as session:
            for original in originals:
                receipt = by_id.get(original.id)
                kind = (
                    "imported"
                    if receipt and receipt.operation == "import_document"
                    else (classify(original.source))
                )
                arrived = receipt.accepted_at if receipt else None
                if receipt and receipt.operation == "upload_audio":
                    arrived = original.created_at
                statement = insert(DocumentMetric).values(
                    user_id=user_id,
                    document_id=original.id,
                    created_at=original.created_at,
                    arrived_at=arrived,
                    kind=kind,
                    deleted=False,
                    seen_at=stamp,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[DocumentMetric.user_id, DocumentMetric.document_id],
                        set_={
                            key: getattr(statement.excluded, key)
                            for key in ("created_at", "arrived_at", "kind", "deleted", "seen_at")
                        },
                    )
                )
            # Preserve evidence of a note deleted before the first successful snapshot.
            # Its original category is unknown; do not claim complete event metrics.
            for receipt in missing:
                statement = insert(DocumentMetric).values(
                    user_id=user_id,
                    document_id=receipt.resource_id,
                    created_at=receipt.accepted_at,
                    arrived_at=receipt.accepted_at,
                    kind="imported" if receipt.operation == "import_document" else None,
                    deleted=True,
                    seen_at=stamp,
                )
                await session.execute(statement.on_conflict_do_nothing())
            await session.execute(
                update(DocumentMetric)
                .where(
                    DocumentMetric.user_id == user_id,
                    DocumentMetric.seen_at != stamp,
                )
                .values(deleted=True)
            )
            statement = insert(InventoryState).values(
                user_id=user_id, complete=True, synced_at=stamp
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[InventoryState.user_id],
                    set_={"complete": True, "synced_at": stamp},
                )
            )
        return len(originals)

    async def run(self):
        async with self.sessions() as lock_session:
            # Advisory lock lives on this connection while account checkpoints commit
            # on separate connections. Crashes release it; reruns are idempotent.
            locked = await lock_session.scalar(select(func.pg_try_advisory_lock(LOCK_ID)))
            if not locked:
                return {"status": "busy", "users": 0, "documents": 0, "failed": 0}
            try:
                async with self.sessions() as session:
                    users = list((await session.scalars(select(User.id).order_by(User.id))).all())
                failed, documents = 0, 0
                for user_id in users:
                    try:
                        if not self.root.is_dir() or self.root.is_symlink():
                            raise ValueError("workspaces_root_unavailable")
                        documents += await self.account(user_id)
                    except (OSError, ValueError):
                        await self.invalidate(user_id)
                        failed += 1
                return {
                    "status": "partial" if failed else "complete",
                    "users": len(users),
                    "documents": documents,
                    "failed": failed,
                }
            finally:
                await lock_session.execute(select(func.pg_advisory_unlock(LOCK_ID)))


async def main(interval):
    try:
        sync = SyncInventory(get_admin_sessions(), get_admin_settings().workspaces_path)
        while True:
            result = await sync.run()
            print(json.dumps(result), flush=True)
            if not interval:
                return 1 if result["failed"] else 0
            await asyncio.sleep(interval)
    finally:
        await close_admin_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="repeat interval in seconds (>=5)")
    args = parser.parse_args()
    if args.interval and args.interval < 5:
        parser.error("--interval must be at least 5 seconds")
    try:
        raise SystemExit(asyncio.run(main(args.interval)))
    except KeyboardInterrupt:
        pass
