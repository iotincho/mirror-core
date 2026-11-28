"""Offline-first evaluation entrypoint; credentials are read only for an explicit live run."""

import os

from src.adapters.access.cli.daily_questions import main
from src.adapters.providers.openai.daily_questions import OpenAIDailyQuestionProvider
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.adapters.storage.memory.question_evaluation import SyntheticQuestionRuntime
from src.bootstrap.ai_usage import ai_usage_scope
from src.bootstrap.database import close_database

_providers = []


class EvaluationQuestionProvider(OpenAIDailyQuestionProvider):
    async def propose(self, data):
        with ai_usage_scope(None, feature_override="daily_question_evaluation"):
            return await super().propose(data)


def provider(configuration):
    instance = EvaluationQuestionProvider(os.environ.get("OPENAI_API_KEY"), configuration)
    _providers.append(instance)
    return instance


async def close_providers():
    try:
        for instance in _providers:
            await instance.close()
    finally:
        _providers.clear()
        await close_database()


async def metrics(days):
    from src.adapters.storage.postgres.question_metrics import PostgresQuestionMetrics
    from src.bootstrap.database import get_session_maker

    try:
        return await PostgresQuestionMetrics(get_session_maker()).aggregate(days)
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(
        main(provider, SyntheticQuestionRuntime, ProcessingArtifacts, metrics, close_providers)
    )
