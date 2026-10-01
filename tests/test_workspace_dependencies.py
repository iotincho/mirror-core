from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.user_management.dependencies import AuthenticatedUser
from src.workspaces.context import UserWorkspaceContext
from src.workspaces.dependencies import (
    WorkspaceBinding,
    build_workspace_runtime,
    get_workspace_binding,
)
from src.workspaces.models import WorkspaceStatus
from src.workspaces.secrets import WorkspaceSecretCipher


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
    workspace = SimpleNamespace(
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

    monkeypatch.setattr("src.workspaces.dependencies.get_settings", lambda: configured)
    monkeypatch.setattr("src.workspaces.dependencies.WorkspaceRepository.get", get)

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
    workspace = SimpleNamespace(status=WorkspaceStatus.PROVISIONING)

    async def get(_: object, requested_user_id: UUID) -> object:
        assert requested_user_id == user_id
        return workspace

    monkeypatch.setattr("src.workspaces.dependencies.get_settings", lambda: configured)
    monkeypatch.setattr("src.workspaces.dependencies.WorkspaceRepository.get", get)

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
    assert runtime.extraction_store._directory == binding.context.filesystem_root / "extractions"
    assert runtime.reflection_store._directory == binding.context.filesystem_root / "reflections"
