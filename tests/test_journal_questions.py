"""Journal catalogs, editorial review and generation scope without external services."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.core.exteriorization.curated_questions import CatalogTopicFact
from src.core.exteriorization.journal_questions import (
    JournalPreparationConfiguration,
    build_journal_questions,
    context_hash,
    context_key,
    journal_topic_id,
)
from src.core.exteriorization.personalization import ProposalProviderConfiguration
from src.core.exteriorization.question_policy import QuestionPolicy, TopicState
from src.core.journals.catalogs import goal_hash
from src.core.journals.contracts import AdjustRun, administrative_run, question_context
from src.core.journals.errors import JournalError
from src.core.journals.models import JournalTemplate
from src.core.journals.ports import MutationReceipt
from src.core.journals.preparation_catalog import PREPARATION_TEMPLATE_V2
from src.core.journals.rules import activate, adjust_remaining_stages, edit_intention


@pytest.fixture
def anyio_backend():
    return "asyncio"


def journey():
    return activate(
        PREPARATION_TEMPLATE_V2,
        run_id=uuid4(),
        owner=uuid4(),
        timezone="UTC",
        now=datetime(2026, 11, 3, 12, tzinfo=UTC),
    )


def test_initial_template_has_curated_depths_for_each_stage_and_occurrence_ids_are_new():
    run = journey()
    for stage in run.stages:
        context = question_context(run.owner_id, run, stage.starts_at)
        assert context.catalog is not None
        assert context.catalog.goal_hash == goal_hash(
            run.purpose, run.instructions, stage.definition
        )
        first = build_journal_questions(
            uuid4(), run.owner_id, context, stage.starts_at, (), QuestionPolicy()
        )
        second = build_journal_questions(
            uuid4(), run.owner_id, context, stage.starts_at, (), QuestionPolicy()
        )
        assert first[1].question_groups[0].questions[1].depth == "middle"
        assert {q.depth for q in first[1].question_groups[0].questions} == {
            "gentle",
            "middle",
            "deep",
        }
        assert set(dict(first[2]).values()) == set(dict(second[2]).values())
        assert set(dict(first[2])) != set(dict(second[2]))


def test_goal_edit_invalidates_catalog_until_explicit_review_but_intention_edit_does_not():
    run = journey()
    at = run.started_at + timedelta(hours=1)
    original = question_context(run.owner_id, run, at)
    edited_intention = edit_intention(
        run, "Comprender mis expectativas", expected_revision=1, now=at
    )
    assert question_context(run.owner_id, edited_intention, at).catalog == original.catalog
    stages = tuple(stage.definition for stage in run.stages)
    adjusted = adjust_remaining_stages(
        run,
        stages,
        expected_revision=1,
        now=at,
        instructions="Invitar a reconocer ejemplos cotidianos",
    )
    changed = question_context(run.owner_id, adjusted, at)
    assert changed.catalog is None and original.catalog is not None
    assert len(administrative_run(adjusted, at).catalog_review_required) == 4
    assert build_journal_questions(uuid4(), run.owner_id, changed, at, (), QuestionPolicy()) is None
    reviewed = tuple(
        item.model_copy(
            update={
                "goal_hash": goal_hash(
                    adjusted.purpose,
                    adjusted.instructions,
                    next(stage for stage in stages if stage.key == item.stage_key),
                )
            }
        )
        for item in run.catalogs
    )
    approved = adjust_remaining_stages(
        adjusted, stages, expected_revision=2, now=at, catalogs=reviewed
    )
    assert question_context(run.owner_id, approved, at).catalog is not None
    assert not administrative_run(approved, at).catalog_review_required
    assert question_context(run.owner_id, run, at).catalog == original.catalog


def test_catalog_review_cannot_rename_topics_or_reuse_an_outdated_goal_approval():
    run = journey()
    at, stages = (
        run.started_at + timedelta(hours=1),
        tuple(stage.definition for stage in run.stages),
    )
    with pytest.raises(JournalError, match="journal_catalog_review_required"):
        adjust_remaining_stages(
            run,
            stages,
            expected_revision=1,
            now=at,
            purpose="Otro propósito",
            catalogs=run.catalogs,
        )
    original = run.catalogs[0]
    renamed = original.model_copy(
        update={
            "prompts": (
                original.prompts[0].model_copy(update={"key": "another-topic"}),
                *original.prompts[1:],
            )
        }
    )
    with pytest.raises(JournalError, match="journal_catalog_topic_identity_changed"):
        adjust_remaining_stages(
            run, stages, expected_revision=1, now=at, catalogs=(renamed, *run.catalogs[1:])
        )


def test_closed_catalog_topics_survive_new_runs_and_all_closed_omits_the_occurrence():
    run = journey()
    context = question_context(run.owner_id, run, run.started_at)
    facts = tuple(
        CatalogTopicFact(
            TopicState(
                id=journal_topic_id(run.owner_id, item.key),
                user_id=run.owner_id,
                scope="catalog",
                status="do_not_prompt",
                restricted_at=run.started_at,
            )
        )
        for item in context.catalog.prompts
    )
    other = activate(
        PREPARATION_TEMPLATE_V2,
        run_id=uuid4(),
        owner=run.owner_id,
        timezone="UTC",
        now=run.started_at,
    )
    other_context = question_context(run.owner_id, other, run.started_at)
    assert (
        build_journal_questions(
            uuid4(), run.owner_id, other_context, run.started_at, facts, QuestionPolicy()
        )
        is None
    )


def test_catalog_rotation_prefers_unseen_then_oldest_recent_topic():
    run = journey()
    at = run.started_at
    context = question_context(run.owner_id, run, at)
    prompts = context.catalog.prompts
    history = tuple(SimpleNamespace(candidate_id=f"journal:{item.key}") for item in prompts)
    selected = build_journal_questions(
        uuid4(), run.owner_id, context, at, (), QuestionPolicy(), history
    )
    assert selected[0].candidate_id == f"journal:{prompts[-1].key}"


def test_context_and_client_cache_identity_have_different_scopes():
    run = journey()
    context = question_context(run.owner_id, run, run.started_at)
    config = JournalPreparationConfiguration(
        model="synthetic-model", journal_reference=context.reference
    )
    changed = edit_intention(run, "Otra intención", expected_revision=1, now=run.started_at)
    next_context = question_context(run.owner_id, changed, run.started_at)
    assert context_key(context.reference) != context_key(next_context.reference)
    assert context_hash(context) != context_hash(next_context)
    assert context_key() == "free"
    technical = ProposalProviderConfiguration.model_validate(
        config.model_dump(
            include=set(ProposalProviderConfiguration.model_fields),
        )
    )
    assert "journal_reference" not in technical.model_dump()
    assert technical.prompt_version == "journal-proposals-v1"


@pytest.mark.anyio
async def test_provider_uses_versioned_journal_rules_without_changing_v1_prompt():
    from src.adapters.providers.openai.daily_questions import (
        PROPOSAL_RULES,
        OpenAIDailyQuestionProvider,
    )
    from src.core.exteriorization.personalization import PreparationConfiguration, TopicProposals

    run = journey()
    context = question_context(run.owner_id, run, run.started_at)
    configurations = (
        PreparationConfiguration(model="synthetic-model"),
        JournalPreparationConfiguration(
            model="synthetic-model", journal_reference=context.reference
        ),
    )
    for configuration in configurations:
        parse = AsyncMock(
            return_value=SimpleNamespace(
                status="completed",
                output_parsed=TopicProposals(proposals=[]),
                usage=None,
            )
        )
        client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        provider = OpenAIDailyQuestionProvider("unused", configuration, client=client)
        await provider.propose(
            {"sources": [], "journal_context": {"purpose": "Exploración sintética"}}
        )
        rules = parse.call_args.kwargs["input"][0]["content"]
        assert parse.call_args.kwargs["store"] is False
        if configuration.version == "daily-preparation-v1":
            assert rules == PROPOSAL_RULES
        else:
            assert rules.startswith(PROPOSAL_RULES) and "CURRENT stage_objective" in rules


@pytest.mark.anyio
async def test_pre_catalog_adjustment_receipt_keeps_its_original_hash():
    from test_journals_application import MemoryJournals

    from src.use_cases.journals.manage import ManageJournals

    fixture = json.loads((Path(__file__).parent / "fixtures/journals_contract_v1.json").read_text())
    repository = MemoryJournals()
    identifier = UUID(fixture["activation"]["run_id"])
    template = JournalTemplate.model_validate(fixture["template"])
    run = activate(
        template, run_id=identifier, owner=repository.owner, timezone="UTC", now=repository.now
    )
    repository.runs[(repository.owner, identifier, 1)] = run
    repository.runs[(repository.owner, identifier, 2)] = adjust_remaining_stages(
        run,
        tuple(stage.definition for stage in run.stages),
        expected_revision=1,
        now=repository.now,
        instructions="Foco de prueba",
    )
    key = uuid4()
    receipt = MutationReceipt(
        key=key,
        owner_id=repository.owner,
        operation="adjust",
        run_id=identifier,
        revision=2,
        request_hash=fixture["legacy_adjust"]["request_hash"],
        recorded_at=repository.now,
    )
    repository.receipts[(repository.owner, key)] = receipt
    command = AdjustRun.model_validate(fixture["legacy_adjust"]["command"])
    assert (
        await ManageJournals(repository).adjust(repository.owner, identifier, command, key)
        == receipt
    )
    assert len(repository.runs) == 2
