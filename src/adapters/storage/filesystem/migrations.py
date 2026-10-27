"""Original fingerprints, verified backups and replayable derived-file removal."""

import asyncio
import hashlib
import json
import os
import shutil
from functools import wraps
from pathlib import Path
from uuid import uuid4

from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.filesystem.durable_files import sync_published


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


def file_call(function):
    @wraps(function)
    async def call(*args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)

    return call


class MigrationFiles:
    def __init__(self, root):
        self.root = Path(root)

    @file_call
    def exists(self):
        return self.root.exists()

    @file_call
    def empty(self):
        return not source_fingerprints(self.root) and not retired_files(self.root)

    @file_call
    def prepare(self):
        self.root.mkdir(parents=True, exist_ok=True)

    async def documents(self):
        return await FileDocumentStore(self.root / "documents").list()

    @file_call
    def inventory(self):
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("Workspace filesystem is unavailable or symlinked")
        files = retired_files(self.root)
        return {
            "sources": source_fingerprints(self.root),
            "files": {
                str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files
            },
        }

    @file_call
    def assert_sources(self, sources):
        if source_fingerprints(self.root) != sources:
            raise ValueError("Filesystem originals changed; transaction aborted")

    @file_call
    def prepare_backup(self, backup, current, expected, operational_history, *, resume):
        backup = Path(backup)
        if (
            backup.resolve() == self.root.resolve()
            or self.root.resolve() in backup.resolve().parents
        ):
            raise ValueError("Backup must be outside the workspace")
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
        return expected

    @file_call
    def remove_derived(self, expected):
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

    @file_call
    def complete(self, backup):
        backup = Path(backup)
        complete = backup / "cleanup.complete"
        complete.write_text("verified\n")
        complete.chmod(0o600)
        sync_published(complete)
