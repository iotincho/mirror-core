"""Approved versions through real SQL reservation, workers and ArcadeDB exploration."""

# ruff: noqa: F811
import asyncio
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.auth.session import require_authenticated
from src.config import get_settings
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ExtractorProfile
from src.extractors.personal_axes.contracts import (
    AxisError,
    AxisSpecification,
    FindingsResponse,
    PreviewRequest,
)
from src.extractors.personal_axes.dependencies import get_axis_previews
from src.extractors.personal_axes.exploration import AxisExploration
from src.extractors.personal_axes.extractor import PersonalAxisExtractor
from src.extractors.personal_axes.repository import AxisRepository
from src.extractors.personal_axes.store import ArcadeDBAxisStore
from src.main import app
from src.use_cases.axis_previews import AxisPreviews
from src.use_cases.delete_document import DeleteDocument
from src.use_cases.process_document_extractors import ProcessDocumentExtractors
from src.use_cases.process_extractor import ProcessExtractor
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import SubmitAudioNote
from src.user_management.models import User

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.getenv("PROCESSING_TEST_DATABASE_URL") and os.getenv("EMOTIONS_TEST_ARCADEDB_URL")),
        reason="requires isolated PostgreSQL and ArcadeDB",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def approve(env, title="Valores", previous=None):
    request = PreviewRequest(
        draft_id=uuid4(),
        revision=1,
        title=title,
        purpose="Reconocer valores personales",
        document_ids=[uuid4() for _ in range(5)],
        axis_id=UUID(previous["id"]) if previous else None,
        base_version_id=UUID(previous["current_version_id"]) if previous else None,
    )
    spec = AxisSpecification(
        profile=ExtractorProfile(id=f"{title}/{uuid4()}", instructions="Reconocer valores e ideas"),
        model="test",
    )
    return await env.axes.accept(
        env.owner, uuid4(), request, spec, datetime.now(UTC) + timedelta(hours=1)
    )


@pytest.fixture
async def active(pipeline, monkeypatch):
    env = pipeline
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(User).where(User.id == env.owner).values(laboratory_enabled=True)
        )
    monkeypatch.setattr(get_settings(), "personal_axes_enabled", True)
    env.axes = AxisRepository(env.repo.sessions)
    env.calls, env.fail, env.empty = Counter(), set(), set()
    legacy = env.registry.definitions[("document", 3)].run.__self__

    class Provider:
        async def extract(self, document, profile):
            env.calls[profile.id] += 1
            if profile.id in env.fail:
                raise ConnectionError("synthetic provider failure")
            return FindingsResponse(
                findings=[]
                if profile.id in env.empty
                else [
                    {
                        "title": title,
                        "content": "Un contenido desarrollado. " * 100,
                        "tags": tags,
                        "evidence": [
                            {"quote": "Hoy siento alegría."},
                            {"quote": "Después sentí miedo."},
                        ],
                    }
                    for title, tags in [
                        ("Valores", ["Crear", "  CREAR ", "Ideas"]),
                        ("Podcast", ["crear", "Podcast"]),
                    ]
                ]
            ), None

    def factory(runtime, spec, *, extracting):
        if spec["name"] != "personal_axis":
            return legacy.extractor_factory(runtime, spec, extracting=extracting)
        return PersonalAxisExtractor(
            runtime.document_store,
            LayerArtifacts(runtime.context.filesystem_root / "layers"),
            spec["specification"],
            Provider() if extracting else None,
            ArcadeDBAxisStore(env.client),
            UUID(spec["axis_id"]),
            UUID(spec["version_id"]),
        )

    env.registry.register(
        "document", 5, ProcessDocumentExtractors(legacy.runtime_factory, keyed=True).definition
    )
    env.registry.register(
        "extractor", 1, ProcessExtractor(legacy.runtime_factory, factory).definition
    )
    env.previews = AxisPreviews(env.repo, env.runtime, get_settings())
    env.explore = AxisExploration(env.previews)
    return env


async def finish(env, parent, *, concurrent=False):
    assert (await run(env, parent)).status == "waiting"
    children = await env.repo.extractor_children(parent.id, env.owner)
    if concurrent:
        await asyncio.gather(*(run(env, child) for child in children))
        # ArcadeDB may reject simultaneous schema/adjacency writes with a
        # transient conflict. Simulate their delayed broker redelivery; persisted
        # extraction artifacts must prevent any second provider invocation.
        for _ in range(3):
            pending = [
                child
                for child in await env.repo.extractor_children(parent.id, env.owner)
                if child.status == "retrying"
            ]
            if not pending:
                break
            for child in pending:
                await run(env, child)
    else:
        for child in children:
            await run(env, child)
    completed = await run(env, parent)
    return completed, await env.repo.extractor_children(parent.id, env.owner)


async def test_two_axis_branches_snapshot_versions_and_idempotent_reservation(active):
    env = active
    a, b = await approve(env), await approve(env, "Podcast")
    key = uuid4()
    document, parent = await upload(env, key)
    assert parent.workflow_version == 5
    pinned = parent.config
    next_a = await approve(env, previous=a)
    await env.axes.set_enabled(env.owner, UUID(b["id"]), False)
    _, replay = await upload(env, key)
    assert replay.id == parent.id and replay.config == pinned
    parent, children = await finish(env, parent, concurrent=True)
    assert parent.status == "completed"
    assert {c.extractor_key for c in children} == {"emotions", f"axis:{a['id']}", f"axis:{b['id']}"}
    assert len({c.id for c in children}) == len({c.extraction_run_id for c in children}) == 3
    assert [c.extractor_name for c in children].count("personal_axis") == 2
    saved = (await env.client.query("SELECT axis_id, version_id FROM AxisExtraction"))["result"]
    assert {r["version_id"] for r in saved} == {a["current_version_id"], b["current_version_id"]}
    assert env.provider.calls == 1 and sum(env.calls.values()) == 2
    # A new reservation uses the new version and respects pause, without retroactive work.
    _, newer = await upload(env)
    axes = [s for s in newer.config["extractors"] if s["name"] == "personal_axis"]
    assert len(axes) == 1 and axes[0]["version_id"] == next_a["current_version_id"]
    assert (await env.graph.get_extraction_graph(str(document.id))).layers == ["emotions"]


async def test_partial_retry_preserves_success_and_old_spec_even_after_pause(active):
    env = active
    a, b = await approve(env), await approve(env, "Podcast")
    failing = b["version"]["specification"]["profile"]["id"]
    env.fail.add(failing)
    env.execute.max_attempts = 1
    _, parent = await upload(env)
    parent, children = await finish(env, parent)
    assert parent.status == "failed" and parent.retryable
    success = [c for c in children if c.status == "completed"]
    assert len(success) == 2
    await approve(env, previous=b)
    await env.axes.set_enabled(env.owner, UUID(b["id"]), False)
    env.fail.clear()
    await RequestProcessing(env.repo, env.runtime).retry(parent.id, uuid4())
    failed = next(c for c in children if c.status == "failed")
    assert (await run(env, failed)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert env.calls[failing] == 2 and sum(env.calls.values()) == 3 and env.provider.calls == 1
    for child in success:
        current = await env.repo.get(child.id, env.owner)
        assert (current.generation, current.attempts) == (child.generation, child.attempts)
    assert a["id"] != b["id"]


async def test_audio_carries_selection_and_reprocess_uses_current_versions(active):
    env = active
    a = await approve(env)
    pinned_b = await approve(env, "Valores de trabajo")
    _, audio = await SubmitAudioNote(env.submit, env.runtime, 1000).execute(
        "note.webm", "audio/webm", b"fixture", None, uuid4()
    )
    b = await approve(env, "Podcast")
    next_a = await approve(env, previous=a)
    await env.axes.set_enabled(env.owner, UUID(a["id"]), False)
    audio = await run(env, audio)
    parent = await env.repo.child(audio)
    assert parent.workflow_version == 5
    assert parent.config["extractors"] == audio.config["extractors"]
    parent, children = await finish(env, parent)
    assert len(children) == 3 and parent.status == "completed"
    assert {
        s.get("axis_id") for s in parent.config["extractors"] if s["name"] == "personal_axis"
    } == {a["id"], pinned_b["id"]}
    assert (await run(env, audio)).status == "completed"
    document = await env.runtime.document_store.get(parent.resource_id)
    reprocessed = await RequestProcessing(env.repo, env.runtime).reprocess_document(
        document.id, uuid4()
    )
    specs = reprocessed.config["extractors"]
    assert {s["axis_id"] for s in specs if s["name"] == "personal_axis"} == {
        b["id"],
        pinned_b["id"],
    }
    reprocessed, _ = await finish(env, reprocessed)
    assert reprocessed.status == "completed" and env.transcriber.calls == 1
    await env.axes.set_enabled(env.owner, UUID(a["id"]), True)
    second = await RequestProcessing(env.repo, env.runtime).reprocess_document(document.id, uuid4())
    assert (
        next(s["version_id"] for s in second.config["extractors"] if s.get("axis_id") == a["id"])
        == next_a["current_version_id"]
    )


async def test_active_branch_pagination_quotes_tags_ownership_and_delete(active):
    env = active
    a, b = await approve(env), await approve(env, "Podcast")
    ids = []
    for _ in range(2):
        document, parent = await upload(env)
        assert (await finish(env, parent))[0].status == "completed"
        ids.append(document.id)
    axis = UUID(a["id"])
    tags = await env.explore.tags(axis, limit=1)
    assert len(tags["items"]) == 1 and tags["items"][0]["key"] == "crear"
    assert tags["items"][0]["document_count"] == 2 and tags["next_cursor"]
    assert (await env.explore.tags(axis, cursor=tags["next_cursor"]))["items"][0]["key"] == "ideas"
    tag_root = tags["items"][0]["id"]
    branch = await env.explore.neighbors(axis, tag_root, limit=1)
    assert len([n for n in branch["nodes"] if n["type"] == "AxisFinding"]) == 1
    quotes = [e for e in branch["edges"] if e["type"] == "HAS_FINDING"]
    assert len(quotes) == 2 and quotes[0]["id"] != quotes[1]["id"]
    assert all(
        e["axis_id"] == a["id"] and e["version_id"] == a["current_version_id"] for e in quotes
    )
    finding = next(n for n in branch["nodes"] if n["type"] == "AxisFinding")
    assert "quote" not in finding and "evidence" not in finding
    assert finding["tags_complete"] and len(finding["source_hash"]) == 64
    assert len([edge for edge in branch["edges"] if edge["type"] == "HAS_TAG"]) == 2
    detail = await env.explore.finding(axis, UUID(finding["finding_id"]))
    assert len(detail["content"]) > 1000 and len(detail["evidence"]) == 2
    outward = await env.explore.neighbors(axis, finding["id"], limit=1)
    assert not next(n for n in outward["nodes"] if n["id"] == finding["id"])["tags_complete"]
    full = await env.explore.neighbors(axis, finding["id"], limit=100)
    assert next(n for n in full["nodes"] if n["id"] == finding["id"])["tags_complete"]
    seen = set()
    quoted = []
    while True:
        seen.update(n["id"] for n in outward["nodes"] if n["id"] != finding["id"])
        quoted.extend(e for e in outward["edges"] if e["type"] == "HAS_FINDING")
        if not outward["next_cursor"]:
            break
        outward = await env.explore.neighbors(
            axis, finding["id"], cursor=outward["next_cursor"], limit=1
        )
    assert len(seen) == len(detail["tags"]) + 1 and len(quoted) == 2
    next_branch = await env.explore.neighbors(axis, tag_root, cursor=branch["next_cursor"], limit=1)
    assert (
        next(n["id"] for n in next_branch["nodes"] if n["type"] == "AxisFinding") != finding["id"]
    )
    with pytest.raises(AxisError, match="axis_cursor_invalid"):
        await env.explore.neighbors(axis, f"Document:{ids[0]}", cursor=branch["next_cursor"])
    with pytest.raises(AxisError, match="axis_node_invalid"):
        await env.explore.neighbors(UUID(b["id"]), tag_root)
    with pytest.raises(AxisError, match="axis_finding_not_found"):
        await env.explore.finding(UUID(b["id"]), UUID(detail["id"]))
    await env.axes.set_enabled(env.owner, axis, False)
    assert (await env.explore.tags(axis))["items"][0]["document_count"] == 2
    env.previews.owner = uuid4()
    with pytest.raises(AxisError, match="axis_not_found"):
        await AxisExploration(env.previews).tags(axis)
    env.previews.owner = env.owner
    await DeleteDocument(
        env.runtime.document_store,
        env.graph,
        env.repo,
        env.owner,
        LayerArtifacts(env.runtime.context.filesystem_root / "layers"),
    ).execute(ids[0])
    assert (await env.explore.tags(axis))["items"][0]["document_count"] == 1
    assert not list(
        (env.runtime.context.filesystem_root / "layers" / str(ids[0])).glob("**/output*")
    )


async def test_version_trace_zero_findings_and_http_contract(active):
    env = active
    a = await approve(env)
    axis = UUID(a["id"])
    assert (await env.explore.tags(axis))["items"] == []
    first, parent = await upload(env)
    await finish(env, parent)
    updated = await approve(env, previous=a)
    second, parent = await upload(env)
    await finish(env, parent)
    old = UUID(a["current_version_id"])
    assert (await env.explore.tags(axis, old))["items"][0]["document_count"] == 1
    assert len((await env.explore.neighbors(axis))["nodes"]) == 3
    env.empty.add(updated["version"]["specification"]["profile"]["id"])
    third, parent = await upload(env)
    await finish(env, parent)
    assert len((await env.explore.neighbors(axis))["nodes"]) == 4
    assert len((await env.explore.neighbors(axis, f"Document:{third.id}"))["nodes"]) == 1
    record = await RequestProcessing(env.repo, env.runtime).reprocess_document(first.id, uuid4())
    await finish(env, record)
    assert (await env.explore.tags(axis, old))["items"] == []
    app.dependency_overrides[get_axis_previews] = lambda: env.previews
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            response = await api.get(
                f"/personal-axes/{axis}/neighbors",
                params={"node_id": f"Document:{second.id}", "limit": 1},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert (
                data["next_cursor"]
                and len([n for n in data["nodes"] if n["type"] == "AxisFinding"]) == 1
            )
            node = next(n for n in data["nodes"] if n["type"] == "AxisFinding")
            detail = await api.get(f"/personal-axes/{axis}/findings/{node['finding_id']}")
            assert detail.status_code == 200 and len(detail.json()["evidence"]) == 2
            assert detail.json()["node_id"] == node["id"]
            assert detail.json()["source_hash"] == node["source_hash"]
            assert node["tags_complete"]
            assert len([edge for edge in data["edges"] if edge["type"] == "HAS_TAG"]) == 2
            listing = await api.get(
                f"/personal-axes/{axis}/findings",
                params={"document_id": str(second.id), "limit": 1},
            )
            assert listing.status_code == 200 and len(listing.json()["items"]) == 1
            assert listing.json()["next_cursor"]
            last = await api.get(
                f"/personal-axes/{axis}/findings",
                params={
                    "document_id": str(second.id),
                    "limit": 1,
                    "cursor": listing.json()["next_cursor"],
                },
            )
            assert last.status_code == 200 and last.json()["next_cursor"] is None
            assert last.json()["items"][0]["id"] != listing.json()["items"][0]["id"]
            assert (
                await api.patch(f"/personal-axes/{axis}", json={"enabled": False})
            ).status_code == 200
            assert (await api.get(f"/personal-axes/{axis}/versions/{old}")).status_code == 200
            assert (
                await api.get(f"/personal-axes/{axis}/neighbors", params={"limit": 0})
            ).status_code == 422
            assert (await api.get(f"/personal-axes/{uuid4()}/tags")).status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_graph_failure_and_invalid_evidence_never_return_empty(active, monkeypatch):
    env = active
    a = await approve(env)
    axis = UUID(a["id"])
    _, parent = await upload(env)
    await finish(env, parent)
    tag = (await env.explore.tags(axis))["items"][0]["id"]
    await env.client.command("UPDATE HAS_AXIS_FINDING SET quote=:bad", {"bad": "invalid"})
    with pytest.raises(AxisError, match="axis_evidence_invalid"):
        await env.explore.neighbors(axis, tag)
    original = env.client.transaction

    def unavailable():
        raise ConnectionError("private material")

    monkeypatch.setattr(env.client, "transaction", unavailable)
    with pytest.raises(AxisError, match="axis_graph_unavailable"):
        await env.explore.tags(axis)
    monkeypatch.setattr(env.client, "transaction", original)


async def test_persistence_retry_uses_artifact_without_provider_and_sanitizes_errors(
    active, monkeypatch, caplog
):
    env = active
    a = await approve(env)
    _, parent = await upload(env)
    env.execute.max_attempts = 1
    original = ArcadeDBAxisStore.write
    private = "PRIVATE_SYNTHETIC_NOTE_PAYLOAD"

    async def failing(*args, **kwargs):
        raise ConnectionError(private)

    monkeypatch.setattr(ArcadeDBAxisStore, "write", failing)
    parent, children = await finish(env, parent)
    branch = next(c for c in children if c.extractor_name == "personal_axis")
    assert parent.status == "failed" and branch.stage == "persistence"
    assert private not in caplog.text
    assert sum(env.calls.values()) == 1
    await approve(env, previous=a)
    await env.axes.set_enabled(env.owner, UUID(a["id"]), False)
    monkeypatch.setattr(ArcadeDBAxisStore, "write", original)
    await RequestProcessing(env.repo, env.runtime).retry(branch.id, uuid4())
    assert (await run(env, branch)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert sum(env.calls.values()) == 1 and env.provider.calls == 1
    assert (await env.client.query("SELECT version_id FROM AxisExtraction"))["result"] == [
        {"version_id": a["current_version_id"]}
    ]


async def test_failed_upload_reservation_keeps_snapshot_and_archive_does_not_add_axes(
    active, monkeypatch
):
    from src.domain.documents import NewDocument, build_document
    from src.use_cases.document_archive import (
        ArchivedDocument,
        DocumentArchive,
        DocumentArchiveTransfer,
    )

    env = active
    a = await approve(env)
    original = env.graph.persist_document

    async def unavailable(document):
        raise ConnectionError("fixture graph unavailable")

    key = uuid4()
    monkeypatch.setattr(env.graph, "persist_document", unavailable)
    with pytest.raises(ConnectionError):
        await upload(env, key)
    pending = await env.submit.get(env.owner, "upload_document", key)
    assert pending.accepted_at is None
    await approve(env, previous=a)
    await env.axes.set_enabled(env.owner, UUID(a["id"]), False)
    monkeypatch.setattr(env.graph, "persist_document", original)
    _, parent = await upload(env, key)
    assert parent.config == pending.config and parent.workflow_version == 5
    assert (await finish(env, parent))[0].status == "completed"
    await env.axes.set_enabled(env.owner, UUID(a["id"]), True)
    # Archive import uses its established baseline, even with active accepted axes.
    monkeypatch.setattr(
        "src.use_cases.document_archive.workflow_config",
        lambda: {"extractors": [], "document_workflow_version": 4},
    )
    document = build_document(NewDocument(content="Original importado"))
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, env.submit, graph=env.graph
    )
    await transfer.import_archive(
        DocumentArchive(
            exported_at=datetime.now(UTC), documents=[ArchivedDocument(**document.model_dump())]
        )
    )
    receipt = await env.submit.get(env.owner, "import_document", document.id)
    imported = await env.repo.get(receipt.processing_id, env.owner)
    assert imported.workflow_version == 2 and imported.config["extractors"] == []
    assert (await run(env, imported)).status == "completed"


async def test_batch_reprocess_pins_once_and_recovers_v5_parent(active):
    from sqlalchemy import update

    from src.processing.models import ProcessingRecord

    env = active
    a = await approve(env)
    documents = []
    for _ in range(2):
        document, parent = await upload(env)
        await finish(env, parent)
        documents.append(document.id)
    newer = await approve(env, previous=a)
    key = uuid4()
    records = await RequestProcessing(env.repo, env.runtime).reprocess_documents(documents, key)
    assert all(r.workflow_version == 5 for r in records)
    await env.axes.set_enabled(env.owner, UUID(a["id"]), False)
    replay = await RequestProcessing(env.repo, env.runtime).reprocess_documents(documents, key)
    assert [r.id for r in replay] == [r.id for r in records]
    assert all(
        next(s["version_id"] for s in r.config["extractors"] if s["name"] == "personal_axis")
        == newer["current_version_id"]
        for r in records
    )
    parent = records[0]
    await run(env, parent)
    children = await env.repo.extractor_children(parent.id, env.owner)
    for child in children:
        await run(env, child)
    # Simulate a missed wake-up after every branch committed; dispatcher recovers v5.
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == parent.id)
            .values(status="waiting")
        )
    await env.repo.recover_parents()
    assert (await env.repo.get(parent.id, env.owner)).status == "queued"
    assert (await run(env, parent)).status == "completed"


async def test_truncated_or_partial_graph_is_an_error(active, monkeypatch):
    env = active
    axis = UUID((await approve(env))["id"])
    _, parent = await upload(env)
    await finish(env, parent)
    original = env.client.query

    async def truncated(*args, **kwargs):
        result = await original(*args, **kwargs)
        result["truncated"] = True
        return result

    monkeypatch.setattr(env.client, "query", truncated)
    with pytest.raises(AxisError, match="axis_graph_unavailable"):
        await env.explore.tags(axis)
    monkeypatch.setattr(env.client, "query", original)
    await env.client.command("DROP TYPE HAS_AXIS_FINDING UNSAFE")
    with pytest.raises(AxisError, match="axis_graph_incomplete"):
        await env.explore.tags(axis)


async def test_database_branch_keys_preserve_legacy_writers_and_reject_duplicates(store):
    from sqlalchemy.exc import IntegrityError

    from src.processing.models import ProcessingRecord

    repo, owner = store
    async with repo.sessions.begin() as session:
        parent = ProcessingRecord(
            user_id=owner,
            workflow="document",
            workflow_version=4,
            resource_kind="document",
            resource_id=uuid4(),
            stage="done",
        )
        session.add(parent)
        await session.flush()

        def child(name, key=None):
            return ProcessingRecord(
                user_id=owner,
                workflow="extractor",
                resource_kind="document",
                resource_id=parent.resource_id,
                parent_processing_id=parent.id,
                extractor_name=name,
                extractor_key=key,
                extraction_run_id=uuid4(),
                stage="extraction",
            )

        legacy = child("emotions")
        session.add(legacy)
        await session.flush()
        await session.refresh(legacy)
        assert legacy.extractor_key == "emotions"
        first = child("personal_axis", f"axis:{uuid4()}")
        second = child("personal_axis", f"axis:{uuid4()}")
        session.add_all([first, second])
        await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(child("personal_axis", first.extractor_key))
                await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(child("personal_axis", ""))
                await session.flush()


async def test_account_access_stops_new_reservations_and_preserves_accepted_work(
    active, monkeypatch
):
    env = active
    axis = await approve(env)
    _, reserved = await upload(env, uuid4())
    assert reserved.workflow_version == 5
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(User).where(User.id == env.owner).values(laboratory_enabled=False)
        )
    _, without_access = await upload(env, uuid4())
    assert all(item["name"] != "personal_axis" for item in without_access.config["extractors"])
    completed, children = await finish(env, reserved)
    assert completed.status == "completed"
    assert any(child.extractor_key == f"axis:{axis['id']}" for child in children)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(User).where(User.id == env.owner).values(laboratory_enabled=True)
        )
    _, restored = await upload(env, uuid4())
    assert restored.workflow_version == 5
    monkeypatch.setattr(get_settings(), "personal_axes_enabled", False)
    _, globally_disabled = await upload(env, uuid4())
    assert all(item["name"] != "personal_axis" for item in globally_disabled.config["extractors"])
