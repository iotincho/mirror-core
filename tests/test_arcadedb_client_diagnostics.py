import io
from urllib.error import HTTPError, URLError

import pytest

from src.graph.arcadedb.client import ArcadeDBClientError, ArcadeDBHTTPClient


@pytest.mark.parametrize("failure", ["http", "connection"])
def test_arcadedb_failures_log_operation_and_status(monkeypatch, caplog, failure):
    def reject(request, timeout):
        if failure == "http":
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"access denied"))
        raise URLError("connection refused")

    monkeypatch.setattr("src.graph.arcadedb.client.urlopen", reject)
    client = ArcadeDBHTTPClient("http://arcade.test", "user_database", "user", "secret-password")
    with pytest.raises(ArcadeDBClientError):
        client.command("MERGE ...", {"content": "Private note"}, language="cypher")

    assert "arcadedb_request_failed" in caplog.text
    assert "operation=command" in caplog.text
    assert "database=user_database" in caplog.text
    assert "language=cypher" in caplog.text
    if failure == "http":
        assert "upstream_status=403" in caplog.text
    else:
        assert "connection refused" in caplog.text
    assert "secret-password" not in caplog.text
    assert "Private note" not in caplog.text
