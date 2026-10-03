"""Model, configuration, and vector-contract failures expose useful diagnostics."""

import logging
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import BadRequestError, NotFoundError, RateLimitError

from src.domain.documents import Document
from src.extraction.profiles import V4_PROFILE
from src.services.embedding_provider import EmbeddingProviderError
from src.services.openai_embedding_provider import OpenAIEmbeddingProvider
from src.services.openai_extractor import OpenAIExtractor
from src.services.structured_extractor import ExtractionProviderError


@pytest.mark.parametrize("kind", ["extraction", "embedding"])
@pytest.mark.parametrize(
    "error_type,status,code,param",
    [
        (NotFoundError, 404, "model_not_found", "model"),
        (RateLimitError, 429, "insufficient_quota", None),
        (BadRequestError, 400, "invalid_dimensions", "dimensions"),
    ],
)
def test_openai_failure_logs_model_status_and_upstream_request_id(
    caplog, kind, error_type, status, code, param,
):
    upstream = httpx.Response(
        status, request=httpx.Request("POST", "https://api.openai.com/test"),
        headers={"x-request-id": "req_provider_test"},
    )
    error = error_type("Provider rejected request", response=upstream, body={
        "code": code, "param": param,
    })

    def reject(**kwargs):
        raise error

    client = SimpleNamespace(
        responses=SimpleNamespace(parse=reject), embeddings=SimpleNamespace(create=reject),
    )
    caplog.set_level(logging.INFO)
    with pytest.raises((ExtractionProviderError, EmbeddingProviderError)) as wrapped:
        if kind == "embedding":
            OpenAIEmbeddingProvider("secret-test-key", "embedding-model", 2, client).embed(
                ["Private note text"],
            )
        else:
            OpenAIExtractor("secret-test-key", "extraction-model", client).extract(
                Document(
                    id=uuid4(), content="Private note text", source="test", metadata={},
                    created_at="2026-10-03T00:00:00Z",
                ), V4_PROFILE,
            )
    assert wrapped.value.__cause__ is error
    assert f"model={kind}-model" in caplog.text
    assert f"'upstream_status': {status}" in caplog.text
    assert "req_provider_test" in caplog.text
    assert code in caplog.text
    assert "stage=request" in caplog.text
    assert "Traceback" in caplog.text
    assert "secret-test-key" not in caplog.text
    assert "Private note text" not in caplog.text


@pytest.mark.parametrize("kind", ["extraction", "embedding"])
def test_missing_api_key_is_logged_as_configuration_failure(caplog, kind):
    caplog.set_level(logging.ERROR)
    with pytest.raises((ExtractionProviderError, EmbeddingProviderError)):
        if kind == "embedding":
            OpenAIEmbeddingProvider(None, "embedding-model", 2).embed(["A note"])
        else:
            OpenAIExtractor(None, "extraction-model").extract(
                Document(
                    id=uuid4(), content="A note", source="test", metadata={},
                    created_at="2026-10-03T00:00:00Z",
                ), V4_PROFILE,
            )
    assert "stage=configuration" in caplog.text
    assert "OPENAI_API_KEY" in caplog.text


def test_vector_dimensions_mismatch_logs_expected_and_actual(caplog):
    client = SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3])],
    )))
    with pytest.raises(EmbeddingProviderError):
        OpenAIEmbeddingProvider("test-key", "embedding-model", 2, client).embed(["A note"])
    assert "stage=response_validation" in caplog.text
    assert "expected_dimensions=2" in caplog.text
    assert "actual_dimensions=[3]" in caplog.text
