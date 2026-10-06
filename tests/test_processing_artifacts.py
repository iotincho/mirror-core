import json

import httpx
import pytest

from src.processing.artifacts import ArtifactCorrupted, ProcessingArtifacts
from src.processing.failures import failure_for


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_artifact_cannot_be_overwritten_or_replayed_for_different_source(tmp_path):
    store = ProcessingArtifacts(tmp_path)
    await store.write("vectors", "original/config", {"vector": [1, 2]})
    assert await store.read("vectors", "original/config") == {"vector": [1, 2]}
    with pytest.raises(ArtifactCorrupted):
        await store.write("vectors", "original/config", {"vector": [3, 4]})
    with pytest.raises(ArtifactCorrupted):
        await store.read("vectors", "another/config")
    path = tmp_path / "vectors.json"
    payload = json.loads(path.read_text())
    payload["payload"]["vector"] = [3, 4]
    path.write_text(json.dumps(payload))
    with pytest.raises(ArtifactCorrupted):
        await store.read("vectors", "original/config")


def test_rate_limit_retry_after_is_respected_and_authentication_is_permanent():
    request = httpx.Request("POST", "https://provider.test")
    error = httpx.HTTPStatusError(
        "private provider text",
        request=request,
        response=httpx.Response(429, headers={"Retry-After": "300"}, request=request),
    )
    failure = failure_for(error, 1, "extraction")
    assert failure.code == "extraction_unavailable" and failure.retry_delay == 300
    assert "private" not in str(failure)
    unauthorized = httpx.HTTPStatusError(
        "secret", request=request, response=httpx.Response(401, request=request)
    )
    assert failure_for(unauthorized, 1, "extraction").retry_delay is None
