from src.config import Settings


def test_settings_read_arcadedb_values_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ARCADEDB_HTTP_URL", "http://graph:2480")
    monkeypatch.setenv("ARCADEDB_DATABASE", "test-db")
    monkeypatch.setenv("ARCADEDB_USERNAME", "test-user")
    monkeypatch.setenv("ARCADEDB_ROOT_PASSWORD", "test-password")

    settings = Settings()

    assert settings.arcadedb_http_url == "http://graph:2480"
    assert settings.arcadedb_database == "test-db"
    assert settings.arcadedb_username == "test-user"
    assert settings.arcadedb_password == "test-password"
