"""Opt-in destructive tests use only a newly created, isolated database."""

import os
from uuid import uuid4

import httpx
import pytest
from legacy_graph_fixture import EmbeddingSpec, legacy_schema_statements
from test_processing_postgres import store  # noqa: F401

from src.domain.documents import NewDocument, build_document
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.arcadedb.schema import schema_statements
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.maintenance.extraction_cleanup import LegacyExtractionCleanup

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("CLEANUP_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def cleanup_database():
    url = os.environ["CLEANUP_TEST_ARCADEDB_URL"]
    password = os.environ["CLEANUP_TEST_ARCADEDB_PASSWORD"]
    name = f"cleanup_test_{uuid4().hex}"
    async with httpx.AsyncClient(base_url=url, auth=("root", password)) as admin:
        response = await admin.post("/api/v1/server", json={"command": f"create database {name}"})
        response.raise_for_status()
        client = AsyncArcadeDBHTTPClient(url, name, "root", password)
        try:
            yield client, (url, name, password)
        finally:
            await client.close()
            response = await admin.post("/api/v1/server", json={"command": f"drop database {name}"})
            response.raise_for_status()


async def test_cleanup_backs_up_and_preserves_sources_and_all_vector_variants(
    cleanup_database, tmp_path
):
    client, connection = cleanup_database
    spec = EmbeddingSpec(provider="fake", model="one", dimensions=3)
    for statement in legacy_schema_statements(spec):
        await client.command(statement)
    for statement in schema_statements():
        await client.command(statement)
    root = tmp_path / "workspace"
    for relative, text in {
        "documents/source.json": "original text",
        "audio-notes/source.webm": "original audio",
        "audio-notes/source.json": "original transcript",
        "extractions/source/run.json": "old extraction",
        "reflections/run.json": "old reflection",
        "processing/job/transcript.json": "durable transcript",
        "processing/job/extraction.json": "old artifact",
        "processing/job/claims.json": "old claim vectors",
        "processing/job/document.json": "old document vector",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    graph = ArcadeDBGraphStore(*connection[:2], "root", connection[2], client=client)
    document = build_document(NewDocument(content="Texto original íntegro", source="manual"))
    await graph.persist_document(document)
    await graph.persist_document(document)
    assert len((await client.query("SELECT FROM Document"))["result"]) == 1
    for name in ("ExtractionRun", "Claim", "Concept", "Entity", "Evidence"):
        await client.command(f"CREATE VERTEX {name} SET id='old-{name}'")
    for base in ("ClaimEmbedding", "DocumentEmbedding"):
        # A vector variant different from the one currently configured.
        await client.command(f"CREATE VERTEX TYPE {base}_old EXTENDS {base}")
        await client.command(f"CREATE VERTEX {base}_old SET id='old-{base}'")
    await client.command(
        "MATCH (c:Claim),(d:Document) CREATE (c)-[:ABOUT {id:'old-link'}]->(d)", language="cypher"
    )
    cleaner = LegacyExtractionCleanup(client, root)
    before = await cleaner.inventory()
    assert before["records"]["ClaimEmbedding_old"]
    assert (root / "extractions/source/run.json").exists()  # inventory is read-only
    after = await cleaner.apply(tmp_path / "backup", before, [{"workflow": "document"}])
    assert after["sources"] == before["sources"]
    assert after["records"]["Document"] == before["records"]["Document"]
    assert all(not values for key, values in after["records"].items() if key != "Document")
    assert not after["files"]
    assert (root / "processing/job/transcript.json").read_text() == "durable transcript"
    assert (tmp_path / "backup/files/extractions/source/run.json").read_text() == "old extraction"
    assert (tmp_path / "backup/processing-history.json").is_file()


async def test_changed_inventory_refuses_cleanup(cleanup_database, tmp_path):
    client, _ = cleanup_database
    for statement in schema_statements():
        await client.command(statement)
    root = tmp_path / "workspace"
    (root / "documents").mkdir(parents=True)
    source = root / "documents/source.json"
    source.write_text("original")
    cleaner = LegacyExtractionCleanup(client, root)
    before = await cleaner.inventory()
    source.write_text("changed")
    with pytest.raises(ValueError, match="Inventory changed"):
        await cleaner.apply(tmp_path / "backup", before)
    assert not (tmp_path / "backup").exists()


@pytest.mark.skipif(
    not os.getenv("PROCESSING_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
)
async def test_cutover_cli_retires_jobs_and_backfills_originals(
    cleanup_database,
    store,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from src.maintenance import cleanup_extractions as cli
    from src.services.document_store import FileDocumentStore

    client, connection = cleanup_database
    repo, owner = store
    spec = EmbeddingSpec(provider="fake", model="one", dimensions=3)
    for statement in legacy_schema_statements(spec) + schema_statements():
        await client.command(statement)
    root = tmp_path / "workspace"
    documents = FileDocumentStore(root / "documents")
    document = build_document(NewDocument(content="Original fuera del grafo", source="manual"))
    await documents.save(document)
    legacy = await repo.create(
        user_id=owner,
        workflow="document",
        stage="extraction",
        resource_kind="document",
        resource_id=document.id,
        config={},
    )
    graph = ArcadeDBGraphStore(*connection[:2], "root", connection[2], client=client)

    @asynccontextmanager
    async def runtime(user_id):
        assert user_id == owner
        yield SimpleNamespace(
            context=SimpleNamespace(filesystem_root=root, database_name=connection[1]),
            graph_store=graph,
            document_store=documents,
        )

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(arcadedb_instance_key="test"))
    monkeypatch.setattr(cli, "get_repository", lambda: repo)
    monkeypatch.setattr(cli, "worker_runtime", runtime)
    args = SimpleNamespace(
        instance="test",
        workspace=owner,
        apply=False,
        services_stopped=False,
        backup=tmp_path / "backup",
    )
    await cli.run(args)
    assert (await repo.get(legacy.id, owner)).status == "queued"
    assert not args.backup.exists()
    args.apply, args.services_stopped = True, True
    await cli.run(args)
    retired = await repo.get(legacy.id, owner)
    assert retired.status == "failed" and retired.error_code == "extraction_retired"
    assert not retired.retryable and retired.generation > legacy.generation
    assert (await documents.get(document.id)).content == document.content
    assert (await client.query("SELECT content FROM Document"))["result"] == [
        {"content": document.content}
    ]
    assert (args.backup / "processing-history.json").exists()
