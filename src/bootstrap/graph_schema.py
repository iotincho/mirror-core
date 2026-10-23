"""Environment and entrypoint for preparing an explicitly selected graph schema."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.adapters.storage.arcadedb.client import ArcadeDBHTTPClient
from src.adapters.storage.arcadedb.schema import SCHEMA_VERSION as SCHEMA_VERSION
from src.adapters.storage.arcadedb.schema import ArcadeDBSchemaError as ArcadeDBSchemaError
from src.adapters.storage.arcadedb.schema import apply_schema as apply_schema
from src.adapters.storage.arcadedb.schema import bootstrap_statements as bootstrap_statements
from src.adapters.storage.arcadedb.schema import migration_version as migration_version
from src.adapters.storage.arcadedb.schema import schema_statements as schema_statements


@dataclass(frozen=True)
class ArcadeDBSchemaConfig:
    http_url: str
    database: str
    username: str
    password: str

    @classmethod
    def from_environment(cls) -> ArcadeDBSchemaConfig:
        return cls(
            http_url=os.getenv("ARCADEDB_HTTP_URL", "http://127.0.0.1:2480").rstrip("/"),
            database=os.getenv("ARCADEDB_DATABASE", "el_espejo"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_ROOT_PASSWORD", "el-espejo-local-password"),
        )


def main() -> int:
    config = ArcadeDBSchemaConfig.from_environment()
    client = ArcadeDBHTTPClient(
        config.http_url,
        config.database,
        config.username,
        config.password,
    )
    applied = apply_schema(client)
    action = "applied" if applied else "already active"
    print(f"ArcadeDB schema {migration_version()} {action}")
    return 0
