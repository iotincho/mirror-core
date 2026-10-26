"""Public composition; legacy history routes remain until stage 4."""

from fastapi import APIRouter

from src.adapters.access.api.public.personal_axes.preview_routes import (
    build_router as build_preview_router,
)
from src.adapters.access.api.public.personal_axes.routes import build_router
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.laboratory import get_laboratory
from src.bootstrap.personal_axes_dependencies import get_preview_cases
from src.bootstrap.personal_axes_reads import get_axis_definitions, get_axis_exploration
from src.bootstrap.public_security import require_same_origin
from src.extractors.personal_axes.routes import router as legacy_router

router = APIRouter()
router.include_router(
    build_router(
        get_authenticated_user,
        get_laboratory,
        get_axis_definitions,
        get_axis_exploration,
        require_same_origin,
    )
)
router.include_router(legacy_router)

router.include_router(build_preview_router(get_preview_cases, require_same_origin))
