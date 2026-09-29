"""Versioned, idempotent ArcadeDB schema initialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from src.embeddings.contracts import EmbeddingSpec
from src.graph.arcadedb.client import ArcadeDBClientError, ArcadeDBHTTPClient

SCHEMA_VERSION = "v1"


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
    embedding_spec: EmbeddingSpec

    @classmethod
    def from_environment(cls) -> ArcadeDBSchemaConfig:
        return cls(
            http_url=os.getenv("ARCADEDB_HTTP_URL", "http://127.0.0.1:2480").rstrip("/"),
            database=os.getenv("ARCADEDB_DATABASE", "el_espejo"),
            username=os.getenv("ARCADEDB_USERNAME", "root"),
            password=os.getenv("ARCADEDB_ROOT_PASSWORD", "el-espejo-local-password"),
            embedding_spec=EmbeddingSpec(
                provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
                model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
                dimensions=int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")),
            ),
        )


def migration_version(spec: EmbeddingSpec) -> str:
    return f"{SCHEMA_VERSION}:{spec.index_suffix}"


def embedding_type_names(spec: EmbeddingSpec) -> tuple[str, str]:
    return (
        f"ClaimEmbedding_{spec.index_suffix}",
        f"DocumentEmbedding_{spec.index_suffix}",
    )


def bootstrap_statements() -> tuple[str, ...]:
    return (
        "CREATE DOCUMENT TYPE SchemaMigration IF NOT EXISTS",
        "CREATE PROPERTY SchemaMigration.version IF NOT EXISTS STRING "
        "(MANDATORY true, NOTNULL true)",
        "CREATE PROPERTY SchemaMigration.applied_at IF NOT EXISTS STRING "
        "(MANDATORY true, NOTNULL true)",
        "CREATE PROPERTY SchemaMigration.embedding_provider IF NOT EXISTS STRING",
        "CREATE PROPERTY SchemaMigration.embedding_model IF NOT EXISTS STRING",
        "CREATE PROPERTY SchemaMigration.embedding_dimensions IF NOT EXISTS INTEGER",
        "CREATE INDEX IF NOT EXISTS ON SchemaMigration (version) UNIQUE",
    )


def schema_statements(spec: EmbeddingSpec) -> tuple[str, ...]:
    claim_embedding_type, document_embedding_type = embedding_type_names(spec)
    statements: list[str] = []

    vertex_properties: dict[str, tuple[tuple[str, str], ...]] = {
        "Document": (
            ("id", "STRING"),
            ("source", "STRING"),
            ("metadata_json", "STRING"),
            ("created_at", "STRING"),
            ("authored_at", "STRING"),
        ),
        "ExtractionRun": (
            ("id", "STRING"),
            ("document_id", "STRING"),
            ("profile_name", "STRING"),
            ("schema_version", "STRING"),
            ("prompt_version", "STRING"),
            ("provider", "STRING"),
            ("model", "STRING"),
            ("created_at", "STRING"),
        ),
        "Concept": (
            ("id", "STRING"),
            ("local_id", "STRING"),
            ("run_id", "STRING"),
            ("document_id", "STRING"),
            ("name", "STRING"),
        ),
        "Entity": (
            ("id", "STRING"),
            ("local_id", "STRING"),
            ("run_id", "STRING"),
            ("document_id", "STRING"),
            ("name", "STRING"),
            ("type", "STRING"),
        ),
        "Claim": (
            ("id", "STRING"),
            ("local_id", "STRING"),
            ("run_id", "STRING"),
            ("document_id", "STRING"),
            ("text", "STRING"),
            ("type", "STRING"),
        ),
        "Evidence": (
            ("id", "STRING"),
            ("run_id", "STRING"),
            ("document_id", "STRING"),
            ("quote", "STRING"),
            ("start_char", "INTEGER"),
            ("end_char", "INTEGER"),
            ("start_line", "INTEGER"),
            ("end_line", "INTEGER"),
        ),
        "ClaimEmbedding": (
            ("id", "STRING"),
            ("claim_graph_id", "STRING"),
            ("claim_local_id", "STRING"),
            ("document_id", "STRING"),
            ("run_id", "STRING"),
            ("profile_name", "STRING"),
            ("prompt_version", "STRING"),
            ("text_hash", "STRING"),
            ("provider", "STRING"),
            ("model", "STRING"),
            ("dimensions", "INTEGER"),
            ("created_at", "STRING"),
        ),
        "DocumentEmbedding": (
            ("id", "STRING"),
            ("document_id", "STRING"),
            ("text_hash", "STRING"),
            ("content", "STRING"),
            ("source", "STRING"),
            ("metadata_json", "STRING"),
            ("created_at", "STRING"),
            ("authored_at", "STRING"),
            ("provider", "STRING"),
            ("model", "STRING"),
            ("dimensions", "INTEGER"),
        ),
    }

    for type_name, properties in vertex_properties.items():
        statements.append(f"CREATE VERTEX TYPE {type_name} IF NOT EXISTS")
        for property_name, property_type in properties:
            constraints = " (MANDATORY true, NOTNULL true)" if property_name == "id" else ""
            statements.append(
                f"CREATE PROPERTY {type_name}.{property_name} IF NOT EXISTS "
                f"{property_type}{constraints}"
            )
        statements.append(f"CREATE INDEX IF NOT EXISTS ON {type_name} (id) UNIQUE")

    for edge_type in (
        "HAS_EXTRACTION",
        "EXTRACTED",
        "SUPPORTED_BY",
        "FROM_DOCUMENT",
        "HAS_EMBEDDING",
    ):
        # ArcadeDB 26.9.1 does not accept UNIQUE and IF NOT EXISTS together in
        # CREATE EDGE TYPE, despite both clauses being valid independently.
        statements.extend(
            (
                f"CREATE EDGE TYPE {edge_type} IF NOT EXISTS",
                f"ALTER TYPE {edge_type} WITH unique = true",
            )
        )

    for edge_type in ("ABOUT", "RELATES_TO", "SUPPORTS", "CONTRADICTS"):
        statements.extend(
            (
                f"CREATE EDGE TYPE {edge_type} IF NOT EXISTS",
                f"CREATE PROPERTY {edge_type}.id IF NOT EXISTS STRING "
                "(MANDATORY true, NOTNULL true)",
                f"CREATE PROPERTY {edge_type}.run_id IF NOT EXISTS STRING",
                f"CREATE PROPERTY {edge_type}.document_id IF NOT EXISTS STRING",
                f"CREATE PROPERTY {edge_type}.evidence_json IF NOT EXISTS STRING",
                f"CREATE INDEX IF NOT EXISTS ON {edge_type} (id) UNIQUE",
            )
        )

    for child_type, parent_type in (
        (claim_embedding_type, "ClaimEmbedding"),
        (document_embedding_type, "DocumentEmbedding"),
    ):
        statements.extend(
            (
                f"CREATE VERTEX TYPE {child_type} IF NOT EXISTS EXTENDS {parent_type}",
                f"CREATE PROPERTY {child_type}.vector IF NOT EXISTS ARRAY_OF_FLOATS",
                f"CREATE INDEX IF NOT EXISTS ON {child_type} (vector) LSM_VECTOR "
                f"METADATA {{ dimensions: {spec.dimensions}, similarity: 'COSINE' }}",
            )
        )

    return tuple(statements)


def apply_schema(client: SchemaClient, spec: EmbeddingSpec) -> bool:
    """Apply the schema once for the core version and exact embedding specification."""
    for statement in bootstrap_statements():
        client.command(statement)

    version = migration_version(spec)
    response = client.query(
        "SELECT count(*) AS count FROM SchemaMigration WHERE version = :version",
        {"version": version},
    )
    results = response.get("result", [])
    if results and int(results[0].get("count", 0)) > 0:
        return False

    for statement in schema_statements(spec):
        client.command(statement)

    client.command(
        "INSERT INTO SchemaMigration SET version = :version, applied_at = :applied_at, "
        "embedding_provider = :provider, embedding_model = :model, "
        "embedding_dimensions = :dimensions",
        {
            "version": version,
            "applied_at": datetime.now(UTC).isoformat(),
            "provider": spec.provider,
            "model": spec.model,
            "dimensions": spec.dimensions,
        },
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
    applied = apply_schema(client, config.embedding_spec)
    action = "applied" if applied else "already active"
    print(f"ArcadeDB schema {migration_version(config.embedding_spec)} {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
