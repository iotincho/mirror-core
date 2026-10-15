from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.use_cases.backfill_document_titles import TitleBackfillResult
from src.use_cases.ensure_document_titles import EnsureDocumentTitles
from src.use_cases.list_documents import ListDocuments


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def scheduler(monkeypatch):
    settings = SimpleNamespace(
        document_title_read_limit=2,
        llm_provider="openai",
        openai_model="test",
        openai_api_key="unused-fake-key",
    )
    backfill = SimpleNamespace(
        owner=uuid4(),
        unavailable=AsyncMock(return_value={}),
        execute=AsyncMock(side_effect=lambda doc, **_: TitleBackfillResult(doc, "queued")),
    )
    monkeypatch.setattr("src.use_cases.ensure_document_titles.get_settings", lambda: settings)
    monkeypatch.setattr(
        "src.use_cases.ensure_document_titles.BackfillDocumentTitles", lambda *_: backfill
    )
    return EnsureDocumentTitles(None, None), settings, backfill


def document(title=None):
    return SimpleNamespace(id=uuid4(), title=title, content="Private original text")


@pytest.mark.anyio
async def test_only_empty_canonical_titles_are_scheduled_with_a_per_read_limit(scheduler):
    ensure, _, backfill = scheduler
    docs = [document("Existing title"), document(None), document("  "), document(None)]
    await ensure.execute(docs)
    assert [call.args[0] for call in backfill.execute.await_args_list] == [docs[1].id, docs[2].id]
    assert all(
        call.kwargs == {"apply": True, "retry_failed": False}
        for call in backfill.execute.await_args_list
    )


@pytest.mark.anyio
async def test_previous_work_does_not_starve_later_untitled_notes(scheduler):
    ensure, _, backfill = scheduler
    docs = [document() for _ in range(103)]
    blocked = {doc.id: TitleBackfillResult(doc.id, "failed") for doc in docs[:100]}
    backfill.unavailable.side_effect = [blocked, {}]
    await ensure.execute(docs)
    assert backfill.unavailable.await_count == 2
    assert [call.args[0] for call in backfill.execute.await_args_list] == [
        docs[100].id,
        docs[101].id,
    ]


@pytest.mark.anyio
async def test_enqueue_failure_is_best_effort_and_logs_no_private_material(scheduler, caplog):
    ensure, _, backfill = scheduler
    backfill.execute.side_effect = OSError("secret note and configuration")
    await ensure.execute([document(), document()])
    assert backfill.execute.await_count == 1
    assert "Title scheduling unavailable" in caplog.text
    assert "secret note" not in caplog.text and "Private original text" not in caplog.text


@pytest.mark.anyio
async def test_disabled_or_unconfigured_scheduling_performs_no_coordination(scheduler):
    ensure, settings, backfill = scheduler
    settings.document_title_read_limit = 0
    await ensure.execute([document()])
    settings.document_title_read_limit = 2
    settings.openai_api_key = None
    await ensure.execute([document()])
    backfill.unavailable.assert_not_called()
    backfill.execute.assert_not_called()


@pytest.mark.anyio
async def test_legacy_list_preserves_originals_and_uses_the_same_scheduler():
    docs = [document()]
    ensure = SimpleNamespace(execute=AsyncMock())
    store = SimpleNamespace(list=AsyncMock(return_value=docs))
    assert await ListDocuments(store, ensure).execute() is docs
    ensure.execute.assert_awaited_once_with(docs)


def test_read_limit_defaults_to_five_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("DOCUMENT_TITLE_READ_LIMIT", raising=False)
    assert Settings(_env_file=None).document_title_read_limit == 5
    assert Settings(_env_file=None, DOCUMENT_TITLE_READ_LIMIT=0).document_title_read_limit == 0
    for invalid in (-1, 101):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, DOCUMENT_TITLE_READ_LIMIT=invalid)
