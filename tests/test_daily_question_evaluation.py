"""Synthetic evaluation, explicit paid budgets, review identity and rollback configuration."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.adapters.access.cli.daily_questions import dataset, implementation_digest, review_report
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.adapters.storage.memory.question_evaluation import SyntheticQuestionRuntime
from src.bootstrap.daily_questions import preparation_configuration, question_policy
from src.bootstrap.settings import Settings
from src.core.exteriorization.evaluation import REVIEW_DIMENSIONS, EvaluationPlan
from src.core.exteriorization.personalization import PreparationConfiguration
from src.core.processing.artifacts import artifact_digest
from src.use_cases.exteriorization.evaluate_questions import evaluate_result, evaluation_input
from src.use_cases.exteriorization.run_question_evaluation import RunQuestionEvaluation

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def plan(mode="reference", **changes):
    value = dict(
        dataset_sha256=artifact_digest(dataset().model_dump(mode="json")),
        implementation_sha256=implementation_digest(),
        mode=mode,
        configuration=PreparationConfiguration(model="synthetic-model"),
        max_calls=16,
    )
    if mode == "live":
        value.update(
            budget_usd=Decimal("1"),
            input_usd_per_million=Decimal("1"),
            output_usd_per_million=Decimal("2"),
            price_source="synthetic unit-test tariffs",
        )
    return EvaluationPlan(**{**value, **changes})


async def test_all_synthetic_reference_cases_pass_without_claiming_llm_quality(tmp_path):
    current, config = dataset(), plan()
    factory = AsyncMock(side_effect=AssertionError("Provider must not be instantiated"))
    result = await RunQuestionEvaluation(
        current, config, ProcessingArtifacts(tmp_path), SyntheticQuestionRuntime, factory
    ).execute("reference")
    assert len(result["cases"]) == 18 and result["automatic_pass"]
    assert result["calls_reserved"] == 0
    assert not result["quality_validated"] and not result["ready_to_enable"]
    factory.assert_not_called()


async def test_live_requires_budget_rates_and_execution_intent_before_any_call(tmp_path):
    with pytest.raises(ValueError):
        plan("live", budget_usd=None)
    with pytest.raises(ValueError):
        plan("live", budget_usd=Decimal("0.01"))
    with pytest.raises(ValueError):
        plan("live", input_usd_per_million=None)
    factory = AsyncMock()
    with pytest.raises(ValueError, match="explicit_execution"):
        await RunQuestionEvaluation(
            dataset(),
            plan("live"),
            ProcessingArtifacts(tmp_path),
            SyntheticQuestionRuntime,
            factory,
        ).execute("live")
    factory.assert_not_called()
    assert not (tmp_path / "plan.json").exists()


async def test_completed_paid_attempts_replay_without_calls_and_still_need_human_review(tmp_path):
    current, config = dataset(), plan("live")
    # All network effects remain simulated; choose the curated reference matching each input.
    pending = [case.reference for case in current.cases if case.notes and case.id != "old_import"]
    provider = SimpleNamespace(
        propose=AsyncMock(
            side_effect=[(value, {"input_tokens": 10, "output_tokens": 10}) for value in pending]
        )
    )
    runner = RunQuestionEvaluation(
        current, config, ProcessingArtifacts(tmp_path), SyntheticQuestionRuntime, lambda _: provider
    )
    first = await runner.execute("live", allow_paid=True)
    second = await runner.execute("live", allow_paid=True)
    assert first == second and first["automatic_pass"]
    assert provider.propose.await_count == len(pending) == 16
    assert first["calls_reserved"] == 16 and not first["quality_validated"]
    paid_cases = [case for case in current.cases if case.notes and case.id != "old_import"]
    payloads = {
        case.id: call.args[0] for case, call in zip(paid_cases, provider.propose.await_args_list)
    }
    shown = payloads["silence_rest"]["history"][0]["questions"][0]
    assert shown["shown"] is True and shown["responses"] == []


async def test_ambiguous_paid_attempt_does_not_retry_automatically(tmp_path):
    artifacts = ProcessingArtifacts(tmp_path)
    await artifacts.write("started-open_intention", "live", {"reserved_call": 1})
    factory = AsyncMock()
    with pytest.raises(ValueError, match="ambiguous_paid_attempt"):
        await RunQuestionEvaluation(
            dataset(), plan("live"), artifacts, SyntheticQuestionRuntime, factory
        ).execute("live", allow_paid=True)
    factory.assert_not_called()


async def test_call_limit_stops_evaluation_without_silently_claiming_success(tmp_path):
    config = plan("live", max_calls=1)
    provider = SimpleNamespace(propose=AsyncMock(return_value=(dataset().cases[0].reference, {})))
    result = await RunQuestionEvaluation(
        dataset(),
        config,
        ProcessingArtifacts(tmp_path),
        SyntheticQuestionRuntime,
        lambda _: provider,
    ).execute("live", allow_paid=True)
    assert provider.propose.await_count == result["calls_reserved"] == 1
    assert not result["automatic_pass"]
    assert any(row.get("error_code") == "call_limit" for row in result["cases"])


async def test_review_is_bound_to_exact_results_and_reference_never_enables(tmp_path):
    result = await RunQuestionEvaluation(
        dataset(), plan(), ProcessingArtifacts(tmp_path), SyntheticQuestionRuntime, None
    ).execute("reference")
    review = dict(
        plan_id="reference",
        results_sha256=artifact_digest(result["cases"]),
        cases={
            row["case_id"]: {key: "pass" for key in REVIEW_DIMENSIONS} for row in result["cases"]
        },
    )
    evaluated = review_report(result, review)
    assert evaluated["human_pass"] and not evaluated["quality_validated"]
    assert not evaluated["ready_to_enable"]
    review["results_sha256"] = "different"
    with pytest.raises(ValueError, match="review_identity"):
        review_report(result, review)


async def test_runtime_policy_is_typed_shared_and_old_configuration_keeps_defaults(monkeypatch):
    monkeypatch.setenv("DAILY_QUESTION_MODEL", "synthetic-model")
    monkeypatch.setenv("DAILY_QUESTION_REST_DAYS", "21")
    settings = Settings(_env_file=None)
    assert settings.daily_question_mode == "curated"
    assert preparation_configuration(settings).policy == question_policy(settings)
    assert question_policy(settings).rest_days == 21
    # Accepted v1 jobs that lack policy use the original defaults, not mutable settings.
    assert PreparationConfiguration(model="synthetic-model").policy.rest_days == 7
    with pytest.raises(ValueError):
        Settings(_env_file=None, DAILY_QUESTION_GENERAL_EVERY=99)


@pytest.mark.parametrize("current_intention", [False, True])
async def test_pause_distinguishes_late_upload_from_new_explicit_intention(current_intention):
    case = next(case for case in dataset().cases if case.id == "pause")
    restriction = case.topics[0].topic.restricted_at
    assert case.notes[0].authored_at < restriction < case.notes[0].accepted_at
    if current_intention:
        case = case.model_copy(
            update={
                "notes": (
                    case.notes[0].model_copy(update={"authored_at": case.now - timedelta(days=1)}),
                ),
                "expected": case.expected.model_copy(
                    update={"initial": "personalized", "min_personal": 1, "max_personal": 2}
                ),
            }
        )
    runtime = SyntheticQuestionRuntime(case, plan().configuration)
    snapshot, _ = await evaluation_input(runtime)
    # Even if the proposer claims reopening, the original authorship must authorize it.
    proposal = case.reference.proposals[0].model_copy(update={"intent": "reopen"})
    value = case.reference.model_copy(update={"proposals": (proposal,)})
    result = await evaluate_result(runtime, snapshot, value)
    assert result["automatic_pass"]
    assert result["initial_source"] == ("personalized" if current_intention else "generic")
