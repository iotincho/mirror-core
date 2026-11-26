"""Exercise the usage schema and repository on disposable PostgreSQL."""

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.providers.openai.daily_questions import OpenAIDailyQuestionProvider
from src.adapters.providers.openai.usage import MeteredOpenAIHttpClient
from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.ai_usage import PostgresAiUsage
from src.adapters.storage.postgres.ai_usage_models import AiUsageCoverage, AiUsageReceipt
from src.core.administration.ai_usage import AiUsageAttempt, AiUsageResult
from src.core.exteriorization.personalization import ProposalProviderConfiguration
from src.core.processing.workflows import WorkflowRegistry

pytestmark = pytest.mark.skipif(
    not os.getenv("AI_USAGE_TEST_DATABASE_URL"), reason="requires isolated AI usage PostgreSQL"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def usage_database(anyio_backend):
    configured = make_url(os.environ["AI_USAGE_TEST_DATABASE_URL"])
    assert configured.database and configured.database.startswith("ai_usage_test")
    database = f"ai_usage_test_{uuid4().hex}"
    target = configured.set(database=database)
    admin = create_async_engine(
        configured.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    engine = create_async_engine(target, hide_parameters=True)

    async def migrate(*arguments):
        await engine.dispose()
        source = (
            "from src.bootstrap.settings import Settings; "
            "Settings.model_config['env_file'] = None; "
            "from alembic.config import main; main()"
        )
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", source, *arguments],
            env={**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
        try:
            yield async_sessionmaker(engine, expire_on_commit=False), migrate
        finally:
            await engine.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{database}"'))
    finally:
        await admin.dispose()


def attempt_for(owner, feature="emotions"):
    return AiUsageAttempt(
        attempt_id=uuid4(),
        user_id=owner,
        execution_id=uuid4(),
        feature=feature,
        provider="openai",
        requested_model="test-model",
    )


@pytest.mark.anyio
async def test_activation_replay_retention_and_downgrade(usage_database):
    sessions, migrate = usage_database
    await migrate("upgrade", "20261120_27")
    owner, second_owner = uuid4(), uuid4()
    async with sessions.begin() as session:
        await session.execute(
            insert(User),
            [
                {"id": owner, "email": "first@example.com", "hashed_password": "unused"},
                {"id": second_owner, "email": "second@example.com", "hashed_password": "unused"},
            ],
        )
    await migrate("upgrade", "head")

    ledger = PostgresAiUsage(sessions)
    attempt = attempt_for(owner)
    audio = attempt_for(second_owner, "transcription")
    pending = attempt_for(owner)
    assert await ledger.start(attempt) is False
    assert await ledger.finish(attempt.attempt_id, AiUsageResult(outcome="unknown")) is False
    await asyncio.gather(*(ledger.maintain(enabled=True, retention_days=90) for _ in range(2)))
    async with sessions() as session:
        first_activation = await session.scalar(select(AiUsageCoverage.started_at))
        assert first_activation is not None
        assert await session.scalar(select(func.count()).select_from(AiUsageCoverage)) == 1

    assert sorted(await asyncio.gather(ledger.start(attempt), ledger.start(attempt))) == [
        False,
        True,
    ]
    assert await ledger.start(attempt.model_copy(update={"user_id": second_owner})) is False
    assert await ledger.start(audio) is True
    assert await ledger.start(pending) is True
    result = AiUsageResult(
        outcome="failed",
        effective_model="test-model-version",
        input_tokens=10,
        output_tokens=0,
        total_tokens=10,
        cached_input_tokens=3,
    )
    assert sorted(
        await asyncio.gather(
            ledger.finish(attempt.attempt_id, result), ledger.finish(attempt.attempt_id, result)
        )
    ) == [False, True]
    assert await ledger.finish(attempt.attempt_id, AiUsageResult(outcome="unknown")) is False

    await ledger.maintain(enabled=False, retention_days=90)
    assert await ledger.start(attempt_for(owner)) is False
    assert (
        await ledger.finish(
            audio.attempt_id, AiUsageResult(outcome="succeeded", duration_seconds=Decimal("3.250"))
        )
        is True
    )
    async with sessions.begin() as session:
        first_period = await session.get(AiUsageCoverage, first_activation)
        first = await session.get(AiUsageReceipt, attempt.attempt_id)
        assert first_period.started_at <= first.started_at <= first_period.ended_at
        assert (first.user_id, first.outcome, first.input_tokens, first.output_tokens) == (
            owner,
            "failed",
            10,
            0,
        )
        for identifier, age in ((audio.attempt_id, 89), (pending.attempt_id, 91)):
            await session.execute(
                update(AiUsageReceipt)
                .where(AiUsageReceipt.attempt_id == identifier)
                .values(started_at=func.now() - timedelta(days=age))
            )
        await session.execute(delete(User).where(User.id == second_owner))

    await ledger.maintain(enabled=False, retention_days=90)
    assert await ledger.finish(pending.attempt_id, AiUsageResult(outcome="unknown")) is False
    await ledger.maintain(enabled=True, retention_days=90)
    async with sessions() as session:
        retained = await session.get(AiUsageReceipt, audio.attempt_id)
        assert retained.user_id is None
        assert retained.duration_seconds == Decimal("3.25") and retained.input_tokens is None
        active = await session.scalar(
            select(AiUsageCoverage.started_at).where(AiUsageCoverage.ended_at.is_(None))
        )
        assert first_period.ended_at <= active
        assert await session.scalar(select(func.count()).select_from(AiUsageReceipt)) == 2

    await ledger.maintain(enabled=False, retention_days=7)
    async with sessions() as session:
        assert await session.get(AiUsageReceipt, audio.attempt_id) is None
        assert await session.get(AiUsageReceipt, attempt.attempt_id) is not None

    await migrate("downgrade", "20261120_27")
    await migrate("upgrade", "head")
    async with sessions() as session:
        assert await session.scalar(select(User.id).where(User.id == owner)) == owner
        assert await session.scalar(select(func.count()).select_from(AiUsageReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(AiUsageCoverage)) == 0


@pytest.mark.anyio
async def test_registered_question_workflows_record_daily_and_journal_usage(
    usage_database, monkeypatch
):
    from src.bootstrap import ai_usage, daily_questions, workflows

    sessions, migrate = usage_database
    await migrate("upgrade", "head")
    ledger = PostgresAiUsage(sessions)
    await ledger.maintain(enabled=True, retention_days=90)
    owners = (uuid4(), uuid4())
    executions = (uuid4(), uuid4())
    async with sessions.begin() as session:
        await session.execute(
            insert(User),
            [
                {"id": owner, "email": f"{n}@example.com", "hashed_password": "unused"}
                for n, owner in enumerate(owners)
            ],
        )

    async def handle(request):
        return httpx.Response(
            200,
            json={
                "id": "response_fixture",
                "model": "effective-question-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"proposals":[]}'}],
                    }
                ],
                "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
            },
        )

    settings = SimpleNamespace(
        daily_question_mode="personalized", journals_enabled=True, ai_usage_enabled=True
    )
    monkeypatch.setattr(workflows, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_usage, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_usage, "get_session_maker", lambda: sessions)
    async with AsyncOpenAI(
        api_key="synthetic-key",
        base_url="https://provider.test/v1",
        max_retries=0,
        http_client=MeteredOpenAIHttpClient(transport=httpx.MockTransport(handle)),
    ) as client:

        def preparation(version=1):
            configuration = ProposalProviderConfiguration(
                model="requested-question-model",
                prompt_version="daily-proposals-v1" if version == 1 else "journal-proposals-v1",
                max_input_tokens=24000,
                max_output_tokens=3000,
                timeout_seconds=10,
                concurrency=2,
            )
            provider = OpenAIDailyQuestionProvider(None, configuration, client=client)

            async def execute(context):
                result, usage = await provider.propose({})
                assert result.proposals == () and usage["input_tokens"] == 8

            return SimpleNamespace(execute=execute)

        monkeypatch.setattr(daily_questions, "build_question_preparation", preparation)
        registry = WorkflowRegistry()
        workflows.register_workflows(registry)
        await asyncio.gather(
            *(
                registry.definitions[("question_preparation", i + 1)].run(
                    SimpleNamespace(record=SimpleNamespace(user_id=owners[i], id=executions[i]))
                )
                for i in range(2)
            )
        )

    async with sessions() as session:
        rows = (await session.scalars(select(AiUsageReceipt))).all()
        assert len(rows) == 2
        by_owner = {row.user_id: row for row in rows}
        for i, feature in enumerate(("daily_question", "journal_question")):
            receipt = by_owner[owners[i]]
            assert (receipt.execution_id, receipt.feature) == (executions[i], feature)
            assert (receipt.input_tokens, receipt.output_tokens, receipt.total_tokens) == (8, 3, 11)
            assert receipt.effective_model == "effective-question-model"
