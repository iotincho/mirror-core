"""Compose the canonical axis extractor and own shared provider clients."""

from functools import lru_cache

from src.adapters.providers.openai.personal_axes import OpenAIAxisProvider
from src.adapters.storage.arcadedb.personal_axes import ArcadeDBAxisStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap.settings import get_settings
from src.core.extractors.personal_axes.models import AxisSpecification
from src.use_cases.extraction.personal_axis import PersonalAxisExtractor


def build_axis_provider(api_key, model, max_output_tokens=6000, client=None):
    settings = get_settings()
    return OpenAIAxisProvider(
        api_key,
        model,
        max_output_tokens,
        client,
        timeout_seconds=settings.provider_timeout_seconds,
        max_concurrency=settings.provider_max_concurrency,
    )


@lru_cache(maxsize=32)
def _provider(provider, model, max_output_tokens):
    if provider != "openai":
        raise ValueError("axis_provider_configuration")
    return build_axis_provider(get_settings().openai_api_key, model, max_output_tokens)


_providers_for_shutdown = set()


def get_axis_provider(configuration):
    provider = _provider(
        configuration["provider"], configuration["model"], configuration["max_output_tokens"]
    )
    _providers_for_shutdown.add(provider)
    return provider


async def close_axis_providers():
    for provider in list(_providers_for_shutdown):
        await provider.close()
    _providers_for_shutdown.clear()
    _provider.cache_clear()


def build_personal_axis_extractor(
    runtime, specification, *, extracting, artifacts=None, write_context=None
):
    spec = AxisSpecification.model_validate(specification["specification"])
    return PersonalAxisExtractor(
        runtime.document_store,
        artifacts or LayerArtifacts(runtime.context.filesystem_root / "layers"),
        spec,
        provider=get_axis_provider(spec.model_dump(exclude={"profile"})) if extracting else None,
        store=ArcadeDBAxisStore(runtime.graph_store.database_client),
        axis_id=specification.get("axis_id"),
        version_id=specification.get("version_id"),
        write_context=write_context,
    )


async def user_workflow_config(session, owner, baseline):
    from src.adapters.storage.postgres.personal_axes.configuration import (
        user_workflow_config as snapshot,
    )

    return await snapshot(session, owner, baseline, enabled=get_settings().personal_axes_enabled)
