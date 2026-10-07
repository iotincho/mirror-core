"""Versioned, idempotent ArcadeDB schema initialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from src.graph.arcadedb.client import ArcadeDBClientError, ArcadeDBHTTPClient

SCHEMA_VERSION = "v5-documents"


class ArcadeDBSchemaError(ArcadeDBClientError):
    """Raised when ArcadeDB rejects or cannot execute a schema migration."""


class SchemaClient(Protocol):
    def command(self, statement: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def query(self, statement: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


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


def migration_version() -> str:
    return SCHEMA_VERSION


def bootstrap_statements() -> tuple[str, ...]:
    return (
        "CREATE DOCUMENT TYPE SchemaMigration IF NOT EXISTS",
        "CREATE PROPERTY SchemaMigration.version IF NOT EXISTS STRING "
        "(MANDATORY true, NOTNULL true)",
        "CREATE PROPERTY SchemaMigration.applied_at IF NOT EXISTS STRING "
        "(MANDATORY true, NOTNULL true)",
        "CREATE INDEX IF NOT EXISTS ON SchemaMigration (version) UNIQUE",
    )


def schema_statements() -> tuple[str, ...]:
    """New workspaces contain originals only; layers will define their own schema."""
    return (
        "CREATE VERTEX TYPE Document IF NOT EXISTS",
        "CREATE PROPERTY Document.id IF NOT EXISTS STRING (MANDATORY true, NOTNULL true)",
        "CREATE PROPERTY Document.content IF NOT EXISTS STRING",
        "CREATE PROPERTY Document.title IF NOT EXISTS STRING",
        "CREATE PROPERTY Document.source IF NOT EXISTS STRING",
        "CREATE PROPERTY Document.metadata_json IF NOT EXISTS STRING",
        "CREATE PROPERTY Document.created_at IF NOT EXISTS STRING",
        "CREATE PROPERTY Document.authored_at IF NOT EXISTS STRING",
        "CREATE INDEX IF NOT EXISTS ON Document (id) UNIQUE",
    )


def apply_schema(client: SchemaClient) -> bool:
    """Apply the schema once for the document schema version."""
    for statement in bootstrap_statements():
        client.command(statement)

    version = migration_version()
    response = client.query(
        "SELECT count(*) AS count FROM SchemaMigration WHERE version = :version",
        {"version": version},
    )
    results = response.get("result", [])
    if results and int(results[0].get("count", 0)) > 0:
        return False

    for statement in schema_statements():
        client.command(statement)

    client.command(
        "INSERT INTO SchemaMigration SET version = :version, applied_at = :applied_at",
        {"version": version, "applied_at": datetime.now(UTC).isoformat()},
    )
    return True


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


if __name__ == "__main__":
    raise SystemExit(main())
