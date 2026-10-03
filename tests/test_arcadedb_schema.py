from src.embeddings.contracts import EmbeddingSpec
from src.graph.arcadedb.schema import (
    apply_schema,
    bootstrap_statements,
    embedding_type_names,
    migration_version,
    schema_statements,
)


class FakeSchemaClient:
    def __init__(self, applied: bool = False) -> None:
        self.applied = applied
        self.commands: list[tuple[str, dict | None]] = []
        self.queries: list[tuple[str, dict | None]] = []

    def command(self, statement: str, params: dict | None = None) -> dict:
        self.commands.append((statement, params))
        return {"result": []}

    def query(self, statement: str, params: dict | None = None) -> dict:
        self.queries.append((statement, params))
        return {"result": [{"count": 1 if self.applied else 0}]}


def embedding_spec() -> EmbeddingSpec:
    return EmbeddingSpec(provider="openai", model="text-embedding-3-small", dimensions=1536)


def test_schema_contains_graph_types_constraints_and_vector_indexes() -> None:
    spec = embedding_spec()
    claim_type, document_type = embedding_type_names(spec)
    statements = schema_statements(spec)

    assert "CREATE VERTEX TYPE Document IF NOT EXISTS" in statements
    assert "CREATE PROPERTY Document.title IF NOT EXISTS STRING" in statements
    assert migration_version(spec).startswith("v4:")
    assert "CREATE EDGE TYPE HAS_EXTRACTION IF NOT EXISTS" in statements
    assert "CREATE EDGE TYPE CROSS_DOCUMENT_LINK IF NOT EXISTS" in statements
    assert "CREATE EDGE TYPE EXPRESSES_EMOTION IF NOT EXISTS" in statements
    assert "ALTER TYPE HAS_EXTRACTION WITH unique = true" in statements
    assert "CREATE INDEX IF NOT EXISTS ON Claim (id) UNIQUE" in statements
    assert f"CREATE VERTEX TYPE {claim_type} IF NOT EXISTS EXTENDS ClaimEmbedding" in statements
    assert (
        f"CREATE VERTEX TYPE {document_type} IF NOT EXISTS EXTENDS DocumentEmbedding"
        in statements
    )
    assert any(
        statement.startswith(f"CREATE INDEX IF NOT EXISTS ON {claim_type} (vector) LSM_VECTOR")
        and "dimensions: 1536" in statement
        for statement in statements
    )


def test_apply_schema_records_exact_embedding_migration() -> None:
    spec = embedding_spec()
    client = FakeSchemaClient()

    assert apply_schema(client, spec) is True

    assert [statement for statement, _ in client.commands[: len(bootstrap_statements())]] == list(
        bootstrap_statements()
    )
    assert client.queries[0][1] == {"version": migration_version(spec)}
    record_statement, record_params = client.commands[-1]
    assert record_statement.startswith("INSERT INTO SchemaMigration")
    assert record_params is not None
    assert record_params["version"] == migration_version(spec)
    assert record_params["dimensions"] == 1536


def test_apply_schema_skips_completed_migration() -> None:
    spec = embedding_spec()
    client = FakeSchemaClient(applied=True)

    assert apply_schema(client, spec) is False

    assert len(client.commands) == len(bootstrap_statements())
