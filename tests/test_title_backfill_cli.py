from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.bootstrap.acceptance import document_title_specification
from src.bootstrap.title_backfill import build_parser, execute
from src.core.extractors.document_title import TITLE_PROFILE
from src.use_cases.documents.backfill_document_titles import (
    BackfillDocumentTitles,
    TitleBackfillResult,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_cli_requires_workspace_defaults_to_preview_and_bounds_queued_jobs():
    owner = uuid4()
    args = build_parser().parse_args(["--workspace", str(owner)])
    assert args.workspace == owner and args.apply is False and args.limit == 100
    assert args.document is None
    for values in ([], ["--workspace", str(owner), "--limit", "0"]):
        with pytest.raises(SystemExit):
            build_parser().parse_args(values)
    doc = uuid4()
    args = build_parser().parse_args(
        ["--workspace", str(owner), "--document", str(doc), "--limit", "1", "--apply"]
    )
    assert args.apply is True and args.document == [doc] and args.limit == 1


def test_title_configuration_is_independent_of_embedding_and_transcription_settings():
    settings = SimpleNamespace(llm_provider="openai", openai_model="pinned-title-model")
    spec = document_title_specification(settings)
    settings.openai_model = "changed"
    assert spec == {
        "name": "document_title",
        "profile": TITLE_PROFILE.model_dump(mode="json"),
        "provider": "openai",
        "model": "pinned-title-model",
    }


@pytest.mark.anyio
async def test_preview_and_apply_use_a_stable_bounded_batch_without_spending_slots_on_busy_docs():
    ids = [UUID(int=i) for i in range(1, 6)]
    statuses = ["busy", "titled", "retryable", "eligible", "eligible"]
    backfill = BackfillDocumentTitles.__new__(BackfillDocumentTitles)
    backfill.owner = uuid4()
    backfill.inspect = AsyncMock(
        side_effect=lambda doc: TitleBackfillResult(doc, statuses[ids.index(doc)])
    )
    backfill.execute = AsyncMock(side_effect=lambda doc, **_: TitleBackfillResult(doc, "retried"))
    preview = await backfill.run(document_ids=list(reversed(ids)) + [ids[0]], limit=1)
    assert preview["counts"] == {"busy": 1, "titled": 1, "retryable": 1, "deferred": 2}
    assert preview["mode"] == "preview" and preview["total_documents"] == 5
    backfill.execute.assert_not_called()
    applied = await backfill.run(document_ids=ids, apply=True, limit=1)
    assert applied["counts"] == {"busy": 1, "titled": 1, "retried": 1, "deferred": 2}
    backfill.execute.assert_awaited_once_with(ids[2], apply=True)
    with pytest.raises(ValueError, match="positive"):
        await backfill.run(limit=0)


@pytest.mark.anyio
async def test_cli_preview_needs_no_llm_credentials_and_does_not_apply(monkeypatch):
    owner = uuid4()
    report = {"mode": "preview", "counts": {"eligible": 1}}
    batch = SimpleNamespace(run=AsyncMock(return_value=report))

    @asynccontextmanager
    async def runtime(user):
        assert user == owner
        yield "bound-workspace"

    def configuration():
        raise AssertionError("Preview must not inspect LLM credentials")

    monkeypatch.setattr("src.bootstrap.title_backfill.worker_runtime", runtime)
    monkeypatch.setattr("src.bootstrap.title_backfill.get_repository", lambda: "repository")
    monkeypatch.setattr("src.bootstrap.title_backfill.get_settings", configuration)
    monkeypatch.setattr("src.bootstrap.title_backfill.BackfillDocumentTitles", lambda *_: batch)
    assert await execute(build_parser().parse_args(["--workspace", str(owner)])) == report
    batch.run.assert_awaited_once_with(apply=False, limit=100, document_ids=None)


@pytest.mark.anyio
async def test_apply_checks_provider_configuration_before_enqueuing(monkeypatch):
    monkeypatch.setattr(
        "src.bootstrap.title_backfill.get_settings",
        lambda: SimpleNamespace(
            llm_provider="openai",
            openai_model=None,
            openai_api_key=None,
        ),
    )
    with pytest.raises(ValueError, match="title_provider_configuration_required"):
        await execute(build_parser().parse_args(["--workspace", str(uuid4()), "--apply"]))
