"""Compose preview application ports and its worker/maintenance workflows."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from src.adapters.storage.filesystem.personal_axes.cleanup import PreviewRoots
from src.adapters.storage.filesystem.personal_axes.previews import PreviewFiles
from src.adapters.storage.postgres.personal_axes.definitions import PostgresAxisDefinitions
from src.adapters.storage.postgres.personal_axes.previews import PostgresPreviews
from src.bootstrap.failures import failure_for
from src.bootstrap.settings import get_settings
from src.core.extractors.personal_axes.previews import PreviewConfiguration
from src.use_cases.personal_axes.expire_previews import ExpireAxisPreviews
from src.use_cases.personal_axes.previews import AxisPreviews
from src.use_cases.personal_axes.process_preview import ProcessAxisPreview


def now():
    return datetime.now(UTC)


def configuration(settings):
    return PreviewConfiguration(
        settings.llm_provider,
        settings.openai_model,
        settings.personal_axes_max_output_tokens,
        settings.personal_axes_max_input_chars,
        settings.personal_axes_max_pending_previews,
        settings.personal_axes_preview_hours,
    )


def build_axis_previews(repository, runtime, settings):
    return AxisPreviews(
        runtime.context.user_id,
        runtime.document_store,
        PreviewFiles(runtime.context.filesystem_root),
        PostgresPreviews(repository),
        PostgresAxisDefinitions(repository.sessions),
        configuration(settings),
        now,
    )


def build_preview_workflow(runtime_factory, provider_factory, settings=None, *, repository=None):
    @asynccontextmanager
    async def previews(owner):
        from src.bootstrap.processing import get_repository

        async with runtime_factory(owner) as runtime:
            yield build_axis_previews(
                repository or get_repository(), runtime, settings or get_settings()
            )

    return ProcessAxisPreview(
        previews,
        provider_factory,
        failure_for,
        (settings or get_settings()).personal_axes_preview_concurrency,
    )


async def expire_axis_previews(repository, settings):
    await ExpireAxisPreviews(
        PostgresPreviews(repository), PreviewRoots(settings.workspaces_path), now
    ).execute()
