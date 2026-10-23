"""Compose this family with common extractors, storage and processing dependencies."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.bootstrap.workspaces import get_workspace_runtime
from src.config import get_settings
from src.core.workspaces.context import WorkspaceRuntime
from src.extractors.artifacts import LayerArtifacts
from src.extractors.personal_axes.access import require_laboratory_access
from src.extractors.personal_axes.contracts import AxisSpecification
from src.extractors.personal_axes.extractor import PersonalAxisExtractor
from src.extractors.personal_axes.provider import OpenAIAxisProvider
from src.extractors.personal_axes.store import ArcadeDBAxisStore


@lru_cache(maxsize=32)
def _provider(provider, model, max_output_tokens):
    if provider != "openai":
        raise ValueError("axis_provider_configuration")
    return OpenAIAxisProvider(get_settings().openai_api_key, model, max_output_tokens)


def axis_provider(configuration):
    return _provider(
        configuration["provider"], configuration["model"], configuration["max_output_tokens"]
    )


async def close_axis_providers():
    # Providers are cached/shared across jobs; ownership remains at process shutdown.
    for provider in list(_providers_for_shutdown):
        await provider.close()
    _providers_for_shutdown.clear()
    _provider.cache_clear()


_providers_for_shutdown = set()


def get_axis_provider(configuration):
    provider = axis_provider(configuration)
    _providers_for_shutdown.add(provider)
    return provider


def build_personal_axis_extractor(runtime, specification, *, extracting, artifacts=None):
    spec = AxisSpecification.model_validate(specification["specification"])
    return PersonalAxisExtractor(
        runtime.document_store,
        artifacts or LayerArtifacts(runtime.context.filesystem_root / "layers"),
        spec,
        provider=get_axis_provider(spec.model_dump(exclude={"profile"})) if extracting else None,
        store=ArcadeDBAxisStore(runtime.graph_store.database_client),
        axis_id=specification.get("axis_id"),
        version_id=specification.get("version_id"),
    )


def get_axis_previews(
    access: Annotated[None, Depends(require_laboratory_access)],
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
):
    from src.processing.runtime import get_repository
    from src.use_cases.axis_previews import AxisPreviews

    settings = get_settings()
    return AxisPreviews(get_repository(), runtime, settings)
