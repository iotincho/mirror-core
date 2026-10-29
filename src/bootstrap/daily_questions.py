"""Compose preparation with owner originals, durable artifacts and the shared runtime."""

import asyncio
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from src.adapters.providers.openai.daily_questions import OpenAIDailyQuestionProvider
from src.adapters.storage.filesystem.owner_originals import FileOwnerOriginals
from src.adapters.storage.filesystem.question_preparations import QuestionPreparationArtifacts
from src.adapters.storage.postgres.question_preparations import PostgresQuestionPreparations
from src.bootstrap.database import get_session_maker
from src.bootstrap.settings import get_settings
from src.core.exteriorization.personalization import PreparationConfiguration
from src.core.processing.errors import WorkflowFailure
from src.use_cases.exteriorization.prepare_questions import PrepareQuestions
from src.use_cases.exteriorization.select_prepared_questions import (
    SelectPreparedQuestions,
    select_proposals,
)


def preparation_configuration(settings):
    model = settings.daily_question_model or settings.openai_model
    if not model:
        raise WorkflowFailure("question_provider_configuration")
    return PreparationConfiguration(
        model=model,
        max_input_tokens=settings.daily_question_max_input_tokens,
        max_output_tokens=settings.daily_question_max_output_tokens,
        timeout_seconds=settings.daily_question_timeout_seconds,
        concurrency=settings.daily_question_concurrency,
        lead_minutes=settings.daily_question_lead_minutes,
    )


def artifact_directory(owner, identifier):
    return (
        get_settings().workspaces_path
        / str(UUID(str(owner)))
        / "daily_questions"
        / str(UUID(str(identifier)))
    )


def artifacts(owner, identifier):
    return QuestionPreparationArtifacts(artifact_directory(owner, identifier))


@lru_cache(maxsize=16)
def provider(configuration):
    return OpenAIDailyQuestionProvider(get_settings().openai_api_key, configuration)


async def close_daily_question_providers():
    # Configuration objects are immutable; accepted jobs use their pinned model/limits.
    for instance in _providers:
        await instance.close()
    _providers.clear()
    provider.cache_clear()


_providers = []


def proposal_provider(configuration):
    instance = provider(configuration)
    if instance not in _providers:
        _providers.append(instance)
    return instance


def build_question_preparation():
    return PrepareQuestions(
        PostgresQuestionPreparations(get_session_maker()),
        FileOwnerOriginals(get_settings().workspaces_path),
        artifacts,
        proposal_provider,
        select_proposals,
    )


def prepared_question_selector():
    settings = get_settings()
    if settings.daily_question_mode != "personalized":
        return None
    return SelectPreparedQuestions(FileOwnerOriginals(settings.workspaces_path))


async def prepare_daily_questions():
    settings = get_settings()
    repository = PostgresQuestionPreparations(get_session_maker())
    now = datetime.now(UTC)
    for owner, identifier in await repository.expired(now):
        await asyncio.to_thread(shutil.rmtree, artifact_directory(owner, identifier), True)
        await repository.remove(owner, identifier)
    if settings.daily_question_mode == "personalized":
        await repository.schedule(preparation_configuration(settings))
