from src.main import app


def test_openapi_no_longer_advertises_exploratory_operations():
    paths = app.openapi()["paths"]
    assert "/search" not in paths
    assert "/resolve" not in paths
    assert "/documents/{document_id}/links" not in paths
    assert "/v2/documents/{document_id}/processing" in paths
