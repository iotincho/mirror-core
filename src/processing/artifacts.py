"""Immutable, hash-checked artifacts for replaying external effects."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


class ArtifactCorrupted(ValueError):
    pass


class ProcessingArtifacts:
    def __init__(self, directory: Path):
        self.directory = directory

    async def read(self, name: str, identity: str):
        def read():
            path = self.directory / f"{name}.json"
            if not path.exists():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["identity"] != identity or value["sha256"] != self.digest(value["payload"]):
                raise ArtifactCorrupted("artifact_identity_mismatch")
            return value["payload"]

        return await asyncio.to_thread(read)

    @staticmethod
    def digest(payload):
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    async def write(self, name: str, identity: str, payload):
        def write():
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{name}.json"
            temporary = self.directory / f"{name}.{uuid4().hex}.tmp"
            value = {"identity": identity, "sha256": self.digest(payload), "payload": payload}
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    path.hardlink_to(temporary)
                except FileExistsError:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if existing != value:
                        raise ArtifactCorrupted("artifact_already_exists")
                descriptor = os.open(self.directory, os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                temporary.unlink(missing_ok=True)

        await asyncio.to_thread(write)
