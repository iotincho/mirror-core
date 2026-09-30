from uuid import UUID

import pytest

from src.config import Settings
from src.workspaces.arcade_admin import RUNTIME_GROUP, ArcadeDBAdminClient, ArcadeDBAdminError
from src.workspaces.repository import workspace_database_name, workspace_graph_username
from src.workspaces.secrets import WorkspaceSecretCipher, WorkspaceSecretError


def workspace_settings(**values: object) -> Settings:
    return Settings(auth_session_secret="a-test-session-secret", **values)


def test_workspace_names_are_opaque_and_deterministic() -> None:
    user_id = UUID("e3f4e7a0-5555-4f28-a7a0-9178d227a4c8")

    assert workspace_database_name(user_id) == "es_e3f4e7a055554f28a7a09178d227a4c8"
    assert workspace_graph_username(user_id) == "es_u_e3f4e7a055554f28a7a09178d227a4c8"


def test_workspace_secret_cipher_derives_a_domain_separated_key() -> None:
    cipher = WorkspaceSecretCipher(workspace_settings())
    ciphertext = cipher.encrypt("technical-password")

    assert ciphertext != "technical-password"
    assert cipher.decrypt(ciphertext) == "technical-password"


def test_workspace_secret_cipher_rejects_an_invalid_explicit_key() -> None:
    with pytest.raises(WorkspaceSecretError):
        WorkspaceSecretCipher(workspace_settings(workspace_secret_key="not-a-fernet-key"))


def test_admin_configures_a_crud_only_runtime_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = ArcadeDBAdminClient("http://arcade.test", "root", "root-password")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        authorization: str | None = None,
    ) -> dict[str, object]:
        calls.append((path, method, payload))
        if path == "/api/v1/server/users":
            return {"result": []}
        return {"result": True}

    monkeypatch.setattr(admin, "_request", request)

    admin.ensure_runtime_principal(
        database_name="es_123",
        username="es_u_123",
        password="technical-password",
    )

    group_payload = calls[0][2]
    assert group_payload is not None
    assert group_payload["name"] == RUNTIME_GROUP
    assert group_payload["access"] == []
    assert group_payload["types"] == {
        "*": {"access": ["createRecord", "readRecord", "updateRecord", "deleteRecord"]}
    }
    user_payload = calls[-1][2]
    assert user_payload == {
        "name": "es_u_123",
        "password": "technical-password",
        "databases": {"es_123": [RUNTIME_GROUP]},
    }


def test_admin_rejects_an_unexpected_runtime_database_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = ArcadeDBAdminClient("http://arcade.test", "root", "root-password")

    class RuntimeClient:
        def __init__(self, *args: object) -> None:
            pass

        def query(self, statement: str) -> dict[str, object]:
            assert statement == "SELECT 1 AS value"
            return {"result": [{"value": 1}]}

    def request_as(*args: object, **kwargs: object) -> dict[str, object]:
        return {"result": ["es_123", "another_database"]}

    monkeypatch.setattr(admin, "_request_as", request_as)
    monkeypatch.setattr("src.workspaces.arcade_admin.ArcadeDBHTTPClient", RuntimeClient)

    with pytest.raises(ArcadeDBAdminError, match="unexpected database scope"):
        admin.verify_runtime_principal(
            database_name="es_123",
            username="es_u_123",
            password="technical-password",
        )
