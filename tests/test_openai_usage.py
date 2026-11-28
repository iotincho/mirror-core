"""Use the real OpenAI SDK with an in-memory HTTP transport and synthetic responses."""

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from src.adapters.providers.openai.document_embeddings import OpenAIDocumentEmbeddingProvider
from src.adapters.providers.openai.document_title import (
    DocumentTitleProviderError,
    OpenAIDocumentTitleProvider,
)
from src.adapters.providers.openai.transcription import OpenAITranscriptionProvider
from src.adapters.providers.openai.usage import MeteredOpenAIHttpClient, attribute_openai_usage
from src.core.extractors.document_title import TITLE_PROFILE


class UsageLedger:
    def __init__(self):
        self.attempts = {}
        self.results = {}
        self.gaps = 0

    async def start(self, attempt):
        created = attempt.attempt_id not in self.attempts
        self.attempts.setdefault(attempt.attempt_id, attempt)
        return created

    async def finish(self, attempt_id, result):
        created = attempt_id not in self.results
        self.results.setdefault(attempt_id, result)
        return created

    def report_failure(self):
        self.gaps += 1

    def for_execution(self, owner, execution=None):
        return attribute_openai_usage(
            self, owner, execution_id=execution, report_failure=self.report_failure
        )


def sdk(handler, *, retries=0):
    return AsyncOpenAI(
        api_key="synthetic-key",
        base_url="https://provider.test/v1",
        max_retries=retries,
        http_client=MeteredOpenAIHttpClient(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_concurrent_embedding_batches_attribute_use_to_their_own_executions(monkeypatch):
    monkeypatch.setattr("src.adapters.providers.openai.document_embeddings.token_count", len)
    ledger = UsageLedger()
    entered, ready = 0, asyncio.Event()
    owners = (uuid4(), uuid4())
    executions = (uuid4(), uuid4())

    async def handle(request):
        nonlocal entered
        entered += 1
        if entered == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 1)
        text = json.loads(request.content)["input"][0]
        tokens = 3 if text == "first" else 7
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [1.0], "object": "embedding"}],
                "model": "effective-embedding-model",
                "object": "list",
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )

    async with sdk(handle) as client:
        provider = OpenAIDocumentEmbeddingProvider(
            "synthetic", "segment-model", client, timeout_seconds=3, max_concurrency=2
        )
        configuration = SimpleNamespace(model="requested-embedding-model", dimensions=1)

        async def embed(index, text):
            with ledger.for_execution(owners[index], executions[index]):
                assert await provider.embed([text], configuration) == [[1.0]]

        await asyncio.gather(embed(0, "first"), embed(1, "second"))
        await provider.embed(["outside measurement"], configuration)

    assert entered == 3
    assert len(ledger.attempts) == len(ledger.results) == 2
    for index, tokens in enumerate((3, 7)):
        attempt = next(
            value for value in ledger.attempts.values() if value.user_id == owners[index]
        )
        result = ledger.results[attempt.attempt_id]
        assert attempt.execution_id == executions[index]
        assert attempt.feature == "document_embeddings"
        assert attempt.requested_model == "requested-embedding-model"
        assert result.effective_model == "effective-embedding-model"
        assert result.input_tokens == result.total_tokens == tokens
        assert result.output_tokens is None


@pytest.mark.anyio
async def test_transcription_counts_each_sdk_retry_and_provider_reported_duration():
    ledger = UsageLedger()
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadError("synthetic network failure", request=request)
        if calls == 2:
            return httpx.Response(500, headers={"retry-after-ms": "1"}, json={"error": {}})
        return httpx.Response(
            200,
            headers={"x-request-id": "req_transcription"},
            json={"text": "example", "usage": {"type": "duration", "seconds": 3.25}},
        )

    class Source:
        async def prepare(self, *, timeout):
            return SimpleNamespace(filename="example.wav", content=b"synthetic audio")

    async with sdk(handle, retries=2) as client:
        provider = OpenAITranscriptionProvider(
            "synthetic", "example-audio-model", client, timeout_seconds=3, max_concurrency=1
        )
        with ledger.for_execution(uuid4()):
            assert await provider.transcribe(Source()) == "example"

    attempts = list(ledger.attempts.values())
    assert len(attempts) == calls == 3
    assert {item.feature for item in attempts} == {"transcription"}
    results = [ledger.results[item.attempt_id] for item in attempts]
    assert [result.outcome for result in results] == ["unknown", "failed", "succeeded"]
    assert [result.duration_seconds for result in results] == [None, None, Decimal("3.25")]
    assert all(result.input_tokens is None for result in results)
    assert results[-1].provider_request_id == "req_transcription"


@pytest.mark.anyio
async def test_usage_is_recorded_even_if_openai_cannot_parse_the_structured_response():
    ledger = UsageLedger()

    async def handle(request):
        return httpx.Response(
            200,
            json={
                "id": "resp_example",
                "model": "effective-text-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"wrong_field":true}'}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "input_tokens_details": {"cached_tokens": 4},
                },
            },
        )

    async with sdk(handle) as client:
        provider = OpenAIDocumentTitleProvider(
            "synthetic", "requested-text-model", client, timeout_seconds=3, max_concurrency=1
        )
        with ledger.for_execution(uuid4()), pytest.raises(DocumentTitleProviderError) as failure:
            await provider.extract(SimpleNamespace(content="example"), TITLE_PROFILE)

    assert isinstance(failure.value.__cause__, ValidationError)
    assert len(ledger.attempts) == len(ledger.results) == 1
    attempt = next(iter(ledger.attempts.values()))
    result = ledger.results[attempt.attempt_id]
    assert attempt.feature == "document_title"
    assert (result.input_tokens, result.cached_input_tokens, result.output_tokens) == (10, 4, 2)
    assert result.provider_request_id == "resp_example"


@pytest.mark.anyio
async def test_storage_loss_after_commit_replays_receipt_without_repeating_provider_request():
    class FlakyLedger(UsageLedger):
        async def start(self, attempt):
            created = await super().start(attempt)
            if created:
                raise RuntimeError("synthetic database disconnect after start")
            return created

        async def finish(self, attempt_id, result):
            created = await super().finish(attempt_id, result)
            if created:
                raise RuntimeError("synthetic database disconnect after finish")
            return created

    ledger = FlakyLedger()
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "example"})

    class Source:
        async def prepare(self, *, timeout):
            return SimpleNamespace(filename="example.wav", content=b"synthetic audio")

    async with sdk(handle) as client:
        provider = OpenAITranscriptionProvider(
            "synthetic", "example-audio-model", client, timeout_seconds=3, max_concurrency=1
        )
        with ledger.for_execution(uuid4()):
            assert await provider.transcribe(Source()) == "example"

    assert len(ledger.attempts) == len(ledger.results) == calls == 1
    assert ledger.gaps == 2
