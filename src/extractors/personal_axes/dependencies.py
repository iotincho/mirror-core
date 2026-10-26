"""Compose this family with common extractors, storage and processing dependencies."""

from typing import Annotated

from fastapi import Depends

from src.bootstrap.settings import get_settings
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.workspaces.context import WorkspaceRuntime
from src.extractors.personal_axes.access import require_laboratory_access


def get_axis_previews(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.bootstrap.processing import get_repository
    from src.use_cases.axis_previews import AxisPreviews

    settings = get_settings()
    return AxisPreviews(get_repository(), runtime, settings)
