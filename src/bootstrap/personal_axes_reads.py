"""Compose definition and exploration ports independently of preview orchestration."""

from typing import Annotated

from fastapi import Depends

from src.adapters.storage.arcadedb.personal_axis_reads import ArcadeDBAxisReads
from src.adapters.storage.postgres.personal_axes.definitions import PostgresAxisDefinitions
from src.bootstrap.laboratory import require_laboratory_access
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.workspaces.context import WorkspaceRuntime
from src.use_cases.personal_axes.definitions import AxisDefinitions
from src.use_cases.personal_axes.exploration import AxisExploration


def build_axis_definitions(sessions, owner):
    return AxisDefinitions(PostgresAxisDefinitions(sessions), owner)


def build_axis_exploration(sessions, runtime, *, owner=None):
    return AxisExploration(
        PostgresAxisDefinitions(sessions),
        ArcadeDBAxisReads(runtime.graph_store.database_client),
        runtime.document_store,
        runtime.context.user_id if owner is None else owner,
    )


def get_axis_definitions(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.processing import get_repository

    return build_axis_definitions(get_repository().sessions, runtime.context.user_id)


def get_axis_exploration(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.processing import get_repository

    return build_axis_exploration(get_repository().sessions, runtime)
