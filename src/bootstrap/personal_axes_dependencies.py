"""Compose this family with common extractors, storage and processing dependencies."""

from typing import Annotated

from fastapi import Depends

from src.bootstrap.laboratory import require_laboratory_access
from src.bootstrap.settings import get_settings
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.workspaces.context import WorkspaceRuntime


def get_axis_previews(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.personal_axes_compat import AxisPreviews
    from src.bootstrap.processing import get_repository

    settings = get_settings()
    return AxisPreviews(get_repository(), runtime, settings)


def get_preview_cases(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.personal_axes_previews import build_axis_previews
    from src.bootstrap.processing import get_repository

    return build_axis_previews(get_repository(), runtime, get_settings())
