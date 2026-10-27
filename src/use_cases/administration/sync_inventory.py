"""Reconcile metadata only; failed reads invalidate coverage and retain previous evidence."""

from datetime import UTC, datetime

from src.core.administration.inventory import InventoryEntry, classify
from src.core.administration.ports import InventoryStore, OriginalMetadataReader


class SyncInventory:
    def __init__(self, store: InventoryStore, originals: OriginalMetadataReader):
        self.store, self.originals = store, originals

    async def account(self, user_id):
        stamp = datetime.now(UTC)
        receipts, previous = await self.store.facts(user_id)
        originals = await self.originals.list(user_id)
        by_id = {}
        for receipt in receipts:
            by_id.setdefault(receipt.resource_id, receipt)
        if originals is None:
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
        entries = []
        for original in originals:
            receipt = by_id.get(original.id)
            kind = (
                "imported"
                if receipt and receipt.operation == "import_document"
                else classify(original.source)
            )
            arrived = receipt.accepted_at if receipt else None
            if receipt and receipt.operation == "upload_audio":
                arrived = original.created_at
            entries.append(InventoryEntry(original.id, original.created_at, arrived, kind, False))
        for receipt in missing:
            entries.append(
                InventoryEntry(
                    receipt.resource_id,
                    receipt.accepted_at,
                    receipt.accepted_at,
                    "imported" if receipt.operation == "import_document" else None,
                    True,
                )
            )
        await self.store.replace(user_id, entries, stamp)
        return len(originals)

    async def run(self):
        async with self.store.guard() as locked:
            if not locked:
                return {"status": "busy", "users": 0, "documents": 0, "failed": 0}
            users = await self.store.owners()
            failed, documents = 0, 0
            for user_id in users:
                try:
                    documents += await self.account(user_id)
                except (OSError, ValueError):
                    await self.store.invalidate(user_id)
                    failed += 1
            return {
                "status": "partial" if failed else "complete",
                "users": len(users),
                "documents": documents,
                "failed": failed,
            }
