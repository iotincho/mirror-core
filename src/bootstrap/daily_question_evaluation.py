"""Offline-first evaluation entrypoint; credentials are read only for an explicit live run."""

import os

from src.adapters.access.cli.daily_questions import main
from src.adapters.providers.openai.daily_questions import OpenAIDailyQuestionProvider
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.adapters.storage.memory.question_evaluation import SyntheticQuestionRuntime

_providers = []


def provider(configuration):
    instance = OpenAIDailyQuestionProvider(os.environ.get("OPENAI_API_KEY"), configuration)
    _providers.append(instance)
    return instance


async def close_providers():
    for instance in _providers:
        await instance.close()
    _providers.clear()


async def metrics(days):
    from src.adapters.storage.postgres.question_metrics import PostgresQuestionMetrics
    from src.bootstrap.database import close_database, get_session_maker

    try:
        return await PostgresQuestionMetrics(get_session_maker()).aggregate(days)
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(
        main(provider, SyntheticQuestionRuntime, ProcessingArtifacts, metrics, close_providers)
    )
