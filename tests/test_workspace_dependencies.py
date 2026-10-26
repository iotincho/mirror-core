from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.adapters.storage.postgres.workspace_models import WorkspaceStatus
from src.bootstrap.settings import Settings
from src.bootstrap.workspaces import (
    WorkspaceSecretCipher,
    build_workspace_runtime,
    get_workspace_binding,
)
from src.core.auth.identity import AuthenticatedUser
from src.core.workspaces.context import UserWorkspaceContext, WorkspaceBinding
from src.core.workspaces.models import Workspace


def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_session_secret="workspace-dependency-test-secret",
        workspaces_path=tmp_path / "users",
    )


@pytest.mark.anyio
async def test_active_workspace_is_resolved_only_from_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = settings(tmp_path)
    user_id = UUID("e3f4e7a0-5555-4f28-a7a0-9178d227a4c8")
    workspace = Workspace(
        user_id=user_id,
        status=WorkspaceStatus.ACTIVE,
        arcadedb_instance_key="primary",
        database_name="es_e3f4e7a055554f28a7a09178d227a4c8",
        graph_username="es_u_e3f4e7a055554f28a7a09178d227a4c8",
        graph_secret_ciphertext=WorkspaceSecretCipher(configured).encrypt("technical-password"),
    )

    async def get(_: object, user_id: UUID) -> object:
        assert user_id == workspace.user_id
        return workspace

    monkeypatch.setattr("src.bootstrap.workspaces.get_settings", lambda: configured)
    monkeypatch.setattr(
        "src.adapters.storage.postgres.workspace_repository.WorkspaceRepository.get", get
    )

    binding = await get_workspace_binding(
        AuthenticatedUser(id=user_id, email="alex@example.com"),
        SimpleNamespace(),
    )

    assert binding.context.user_id == user_id
    assert binding.context.filesystem_root == tmp_path / "users" / str(user_id)
    assert binding.graph_secret == "technical-password"


@pytest.mark.anyio
async def test_unready_workspace_does_not_expose_storage_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = settings(tmp_path)
    user_id = UUID("e3f4e7a0-5555-4f28-a7a0-9178d227a4c8")
    workspace = Workspace(
        user_id, "primary", "unused", "unused", "unused", status=WorkspaceStatus.PROVISIONING
    )

    async def get(_: object, requested_user_id: UUID) -> object:
        assert requested_user_id == user_id
        return workspace

    monkeypatch.setattr("src.bootstrap.workspaces.get_settings", lambda: configured)
    monkeypatch.setattr(
        "src.adapters.storage.postgres.workspace_repository.WorkspaceRepository.get", get
    )

    with pytest.raises(HTTPException) as error:
        await get_workspace_binding(
            AuthenticatedUser(id=user_id, email="alex@example.com"),
            SimpleNamespace(),
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Personal workspace is preparing"


def test_runtime_builds_every_file_store_under_one_workspace_root(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    user_id = UUID("e3f4e7a0-5555-4f28-a7a0-9178d227a4c8")
    binding = WorkspaceBinding(
        context=UserWorkspaceContext(
            user_id=user_id,
            arcadedb_instance_key="primary",
            database_name="es_e3f4e7a055554f28a7a09178d227a4c8",
            graph_username="es_u_e3f4e7a055554f28a7a09178d227a4c8",
            filesystem_root=tmp_path / "users" / str(user_id),
        ),
        graph_secret="technical-password",
    )

    runtime = build_workspace_runtime(binding, configured)

    assert runtime.document_store._directory == binding.context.filesystem_root / "documents"
    assert runtime.audio_note_store._directory == binding.context.filesystem_root / "audio-notes"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [WorkspaceStatus.ACTIVE, WorkspaceStatus.PROVISIONING])
async def test_invalid_cipher_config_keeps_public_setup_safe_and_worker_failure_retryable(
    monkeypatch,
    tmp_path,
    status,
):
    from src.bootstrap.workflows import worker_runtime
    from src.bootstrap.workspaces import workspace_access
    from src.core.workspaces.errors import WorkspaceSecretError

    configured = settings(tmp_path)
    configured.workspace_secret_key = "invalid-fernet-key"
    owner = UUID("e3f4e7a0-5555-4f28-a7a0-9178d227a4c8")
    workspace = Workspace(
        owner, configured.arcadedb_instance_key, "unused", "unused", "unused", status=status
    )

    async def read(_store, requested):
        assert requested == owner
        return workspace

    monkeypatch.setattr("src.bootstrap.workspaces.get_settings", lambda: configured)
    monkeypatch.setattr("src.adapters.storage.postgres.workspaces.PostgresWorkspaces.read", read)
    access = workspace_access(settings=configured)
    assert await access.status(owner) == ("unavailable" if status == "active" else "provisioning")
    with pytest.raises(HTTPException) as failure:
        await get_workspace_binding(
            AuthenticatedUser(owner, "owner@example.test"), SimpleNamespace()
        )
    assert failure.value.status_code == 503
    expected = (
        "Personal workspace is unavailable"
        if status == "active"
        else "Personal workspace is preparing"
    )
    assert failure.value.detail == expected
    if status == "active":
        monkeypatch.setattr("src.bootstrap.workflows.workspace_access", lambda **_: access)
        with pytest.raises(WorkspaceSecretError):
            async with worker_runtime(owner):
                pytest.fail("Invalid workspace credentials must not construct a runtime")
