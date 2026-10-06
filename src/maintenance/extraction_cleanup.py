"""Inventory, back up and remove historical extraction data in one workspace."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from src.services.durable_files import sync_published

LEGACY_VERTICES = {
    "ExtractionRun",
    "Concept",
    "Entity",
    "Claim",
    "Evidence",
    "ClaimEmbedding",
    "DocumentEmbedding",
}
LEGACY_EDGES = {
    "HAS_EXTRACTION",
    "EXTRACTED",
    "SUPPORTED_BY",
    "FROM_DOCUMENT",
    "HAS_EMBEDDING",
    "CROSS_DOCUMENT_LINK",
    "ABOUT",
    "RELATES_TO",
    "SUPPORTS",
    "CONTRADICTS",
    "EXPRESSES_EMOTION",
    "DESIRES",
    "FEARS",
    "VALUES",
    "QUESTIONS",
    "DECIDES",
    "ASSOCIATES_WITH",
}


def rows(response):
    if response.get("truncated"):
        raise ValueError("Inventory response was truncated; cleanup refused")
    return response.get("result", [])


def source_fingerprints(root):
    result = {}
    for name in ("documents", "audio-notes"):
        directory = root / name
        if directory.is_symlink():
            raise ValueError("Symlinked source directory; cleanup refused")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Symlinked source file; cleanup refused")
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def retired_files(root):
    # Keep transcripts and unknown artifacts. Remove only extraction/vector checkpoints.
    result = []
    for name in ("extractions", "reflections", "processing"):
        directory = root / name
        if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob("*")):
            raise ValueError("Symlinked artifact directory; cleanup refused")
    for name in ("extractions", "reflections"):
        result.extend(path for path in (root / name).rglob("*") if path.is_file())
    for name in ("extraction.json", "claims.json", "document.json"):
        result.extend((root / "processing").glob(f"*/{name}"))
    for path in result:
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise ValueError("Artifact outside workspace; cleanup refused")
    return sorted(set(result))


class LegacyExtractionCleanup:
    def __init__(self, client, root):
        self.client, self.root = client, Path(root)

    async def inventory(self):
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("Workspace filesystem is unavailable or symlinked")
        schema = rows(await self.client.query("SELECT name, type, parentTypes FROM schema:types"))
        targets = {
            item["name"] for item in schema if item["name"] in LEGACY_VERTICES | LEGACY_EDGES
        }
        # Include every vector specification, not just the current embedding model.
        changed = True
        while changed:
            changed = False
            for item in schema:
                if set(item.get("parentTypes", [])) & targets and item["name"] not in targets:
                    targets.add(item["name"])
                    changed = True
        for name in targets:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
                raise ValueError("Unexpected schema identifier")
        records = {}
        for name in sorted(targets | {"Document"}):
            if name in {item["name"] for item in schema}:
                records[name] = rows(await self.client.query(f"SELECT FROM `{name}`"))
        files = retired_files(self.root)
        return {
            "schema": schema,
            "records": records,
            "sources": source_fingerprints(self.root),
            "files": {
                str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files
            },
        }

    async def apply(self, backup, expected, operational_history=None, *, resume=False):
        backup = Path(backup)
        if (
            backup.resolve() == self.root.resolve()
            or self.root.resolve() in backup.resolve().parents
        ):
            raise ValueError("Backup must be outside the workspace")
        current = await self.inventory()
        if backup.exists():
            if not resume or backup.is_symlink() or not (backup / "backup.ready").is_file():
                raise ValueError("Backup destination already exists or is incomplete")
            original = json.loads((backup / "inventory.json").read_text())
            if current["sources"] != original["sources"]:
                raise ValueError("Originals changed since backup; migration refused")
            for relative, digest in (original["sources"] | original["files"]).items():
                saved = backup / "files" / relative
                if not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest() != digest:
                    raise ValueError("Backup verification failed")
            if any(
                original["files"].get(name) != digest for name, digest in current["files"].items()
            ):
                raise ValueError("New or changed derived files; migration refused")
            for name, records in current["records"].items():
                if name != "Document" and any(
                    row not in original["records"].get(name, []) for row in records
                ):
                    raise ValueError("New derived records since backup; migration refused")
            if not (backup / "cleanup.complete").exists():
                if current["records"].get("Document", []) != original["records"].get(
                    "Document", []
                ):
                    raise ValueError("Graph originals changed since backup")
            expected = current
        else:
            if current != expected:
                raise ValueError("Inventory changed; cleanup refused")
            # Publish only a complete, verified backup. Interrupted staging directories
            # remain as evidence, but cannot be mistaken for a resumable backup.
            staging = backup.with_name(f"{backup.name}.preparing-{uuid4().hex}")
            staging.mkdir(parents=True, exist_ok=False, mode=0o700)
            snapshot = staging / "inventory.json"
            snapshot.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
            snapshot.chmod(0o600)
            sync_published(snapshot)
            if operational_history is not None:
                history = staging / "processing-history.json"
                history.write_text(json.dumps(operational_history, default=str, indent=2) + "\n")
                history.chmod(0o600)
                sync_published(history)
            for relative, digest in (expected["sources"] | expected["files"]).items():
                destination = staging / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / relative, destination)
                destination.chmod(0o600)
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ValueError("Backup verification failed")
                sync_published(destination)
            ready = staging / "backup.ready"
            ready.write_text("verified\n")
            ready.chmod(0o600)
            sync_published(ready)
            staging.rename(backup)
            descriptor = os.open(backup.parent, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        targets = set(expected["records"]) - {"Document"}
        kinds = {item["name"]: item["type"] for item in expected["schema"]}
        # Child types first; SQL includes subtypes, so deletion is safely replayable.
        async with self.client.transaction() as transaction:
            for name in sorted(targets, key=lambda n: (kinds[n] != "edge", -len(n), n)):
                await transaction.command(f"DELETE FROM `{name}`")
            preserved = rows(await transaction.query("SELECT FROM Document"))
            if preserved != expected["records"].get("Document", []):
                raise ValueError("Graph originals changed; transaction aborted")
            if source_fingerprints(self.root) != expected["sources"]:
                raise ValueError("Filesystem originals changed; transaction aborted")
            for name in targets:
                if rows(await transaction.query(f"SELECT FROM `{name}`")):
                    raise ValueError("Derived graph records remain; transaction aborted")
        # Schemas/index definitions remain empty to avoid global or inherited DDL damage.
        for relative, digest in expected["files"].items():
            path = self.root / relative
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Artifact changed; filesystem cleanup stopped")
            path.unlink()
            descriptor = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        after = await self.inventory()
        if after["sources"] != expected["sources"] or after["files"]:
            raise ValueError("Post-cleanup filesystem verification failed")
        if after["records"].get("Document", []) != expected["records"].get("Document", []):
            raise ValueError("Post-cleanup graph verification failed")
        complete = backup / "cleanup.complete"
        complete.write_text("verified\n")
        complete.chmod(0o600)
        sync_published(complete)
        return after
