"""Bind the owner of a production execution to the OpenAI usage recorder."""

from contextlib import nullcontext
from uuid import UUID

from src.adapters.providers.openai.usage import attribute_openai_usage
from src.adapters.storage.postgres.ai_usage import PostgresAiUsage
from src.bootstrap.database import get_session_maker
from src.bootstrap.observability import report_issue
from src.bootstrap.settings import get_settings


def ai_usage_scope(
    user_id: UUID | None, execution_id: UUID | None = None, *, feature_override: str | None = None
):
    if not get_settings().ai_usage_enabled:
        return nullcontext()
    return attribute_openai_usage(
        PostgresAiUsage(get_session_maker()),
        user_id,
        execution_id=execution_id,
        report_failure=lambda: report_issue("ai_usage_recording_failed"),
        feature_override=feature_override,
    )
