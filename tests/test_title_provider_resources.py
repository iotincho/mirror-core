"""Explicit provider configuration and client ownership across composition changes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.adapters.providers.openai.document_title import OpenAIDocumentTitleProvider
from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.document_title import TITLE_PROFILE, DocumentTitle
from src.core.processing.errors import WorkflowFailure


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("borrowed", [False, True])
async def test_explicit_limits_and_sdk_retry_policy_and_client_ownership(monkeypatch, borrowed):
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(
            output_parsed=DocumentTitle(title="Un día tranquilo"),
        ))),
        close=AsyncMock(),
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr("openai.AsyncOpenAI", factory)
    provider = OpenAIDocumentTitleProvider(
        "fake", "accepted-model", client if borrowed else None,
        timeout_seconds=9, max_concurrency=1, max_retries=0,
    )
    await provider.extract(build_document(NewDocument(content="Un día tranquilo.")), TITLE_PROFILE)
    if borrowed:
        factory.assert_not_called()
    else:
        factory.assert_called_once_with(api_key="fake", timeout=9, max_retries=0)
    await provider.close()
    await provider.close()
    assert client.close.await_count == (0 if borrowed else 1)


@pytest.mark.anyio
async def test_unconfigured_provider_keeps_safe_retryable_failure_without_sdk_creation(monkeypatch):
    factory = Mock(side_effect=AssertionError("SDK must remain uninitialized"))
    monkeypatch.setattr("openai.AsyncOpenAI", factory)
    provider = OpenAIDocumentTitleProvider(
        None, None, timeout_seconds=9, max_concurrency=1, max_retries=0,
    )
    with pytest.raises(WorkflowFailure) as failure:
        await provider.extract(build_document(NewDocument(content="Original.")), TITLE_PROFILE)
    assert failure.value.code == "provider_configuration" and failure.value.retryable
    factory.assert_not_called()
