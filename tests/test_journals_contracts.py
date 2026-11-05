"""Synthetic stage-1 journal behavior; no database, broker, API or paid provider."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.core.journals.calendar import local_instant
from src.core.journals.contracts import (
    ActivateRun,
    AdjustRun,
    ChangeLifecycle,
    EditIntention,
    EntryReference,
    FreeQuestionContext,
    JournalQuestionContext,
    ResponseJournalContext,
    administrative_run,
    public_run,
    question_context,
    validate_entry_reference,
)
from src.core.journals.errors import JournalError
from src.core.journals.models import JournalRun, JournalTemplate, StageDefinition
from src.core.journals.rules import (
    activate,
    adjust_remaining_stages,
    advance,
    close,
    edit_intention,
    effective_status,
    pause,
    reconcile,
    resume,
    stage_at,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures/journals_contract_v1.json").read_text())
TEMPLATE = JournalTemplate.model_validate(FIXTURE["template"])
OWNER = UUID(FIXTURE["activation"]["owner"])
START = datetime.fromisoformat(FIXTURE["activation"]["now"])


def journey(**overrides):
    values = {
        **FIXTURE["activation"],
        "run_id": UUID(FIXTURE["activation"]["run_id"]),
        "owner": OWNER,
        "now": START,
        **overrides,
    }
    return activate(TEMPLATE, **values)


def changed(definition, **changes):
    return StageDefinition.model_validate({**definition.model_dump(), **changes})


def test_template_fixture_and_activation_are_independent_immutable_snapshots():
    run = journey()
    assert TEMPLATE.model_dump(mode="json") == FIXTURE["template"]
    assert [stage.ends_at for stage in run.stages] == [
        datetime.fromisoformat(value) for value in FIXTURE["boundaries"]
    ]
    assert run.started_at == START
    assert run.stages[0].ends_at - START == timedelta(days=6, hours=12)
    other = journey(run_id=uuid4())
    assert {stage.id for stage in run.stages}.isdisjoint(stage.id for stage in other.stages)
    assert run.template_id == other.template_id
    with pytest.raises(ValidationError):
        run.stages[0].definition.duration_days = 9
    updated = TEMPLATE.model_copy(update={"purpose": "Otra definición", "version": 2})
    assert run.purpose != updated.purpose and run.template_version == 1


def test_stage_boundaries_and_multiple_days_without_a_dispatcher():
    run = journey()
    for index, stage in enumerate(run.stages):
        assert stage_at(run, stage.starts_at) == stage
        assert stage_at(run, stage.ends_at - timedelta(microseconds=1)) == stage
        expected = run.stages[index + 1] if index + 1 < len(run.stages) else None
        assert stage_at(run, stage.ends_at) == expected
    assert stage_at(run, START - timedelta(seconds=1)) is None
    day_twenty = START + timedelta(days=20)
    assert stage_at(run, day_twenty) == run.stages[2]
    assert public_run(run, day_twenty).current_stage_id == run.stages[2].id
    assert run.revision == 1  # Ordinary advancement is calendar-derived, not a daily mutation.


@pytest.mark.parametrize(
    ("start", "hours"),
    [
        ("2026-03-07T05:00:00+00:00", 167),
        ("2026-10-31T04:00:00+00:00", 169),
    ],
)
def test_seven_calendar_days_cross_daylight_saving(start, hours):
    run = journey(now=datetime.fromisoformat(start), timezone="America/New_York")
    assert run.stages[0].ends_at - run.started_at == timedelta(hours=hours)
    assert run.stages[0].ends_at.tzinfo == UTC


def test_missing_midnight_and_repeated_wall_time_have_explicit_resolution():
    assert local_instant(datetime(2018, 11, 4), "America/Sao_Paulo") == datetime(
        2018, 11, 4, 3, tzinfo=UTC
    )
    assert local_instant(datetime(2026, 11, 1, 1, 30), "America/New_York") == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_context_is_for_the_occurrence_even_before_the_next_stage_starts():
    run = journey()
    due = run.stages[1].starts_at
    early = question_context(OWNER, run, due - timedelta(minutes=30))
    prepared = question_context(OWNER, run, due)
    assert early.reference.stage_id == run.stages[0].id
    assert prepared.reference.stage_id == run.stages[1].id
    assert prepared.stage_objective == run.stages[1].definition.objective
    assert prepared.reference.run_revision == run.revision


def test_completion_is_effective_before_reconciliation_and_reconciles_once():
    run = journey()
    end = run.stages[-1].ends_at
    assert effective_status(run, end) == "completed"
    assert public_run(run, end).status == "completed"
    assert isinstance(question_context(OWNER, run, end), FreeQuestionContext)
    completed = reconcile(run, now=end + timedelta(days=4))
    assert completed.status == "completed" and completed.ended_at == end
    assert completed.revision == 2
    assert reconcile(completed, now=end + timedelta(days=5)) is completed
    assert run.status == "active"


def test_one_active_per_owner_and_repeat_template_after_completion():
    first = journey()
    with pytest.raises(JournalError, match="journal_active_conflict"):
        journey(run_id=uuid4(), existing=(first,))
    foreign = journey(owner=uuid4(), existing=(first,))
    assert foreign.owner_id != first.owner_id
    later = journey(now=first.stages[-1].ends_at, run_id=uuid4(), existing=(first,))
    assert later.template_id == first.template_id and later.id != first.id


def test_pause_resume_freezes_remaining_time_and_preserves_completed_stages():
    run = journey()
    at = run.stages[1].starts_at + timedelta(hours=12)
    paused = pause(run, expected_revision=1, now=at)
    assert isinstance(question_context(OWNER, paused, at), FreeQuestionContext)
    assert paused.paused_at == at and paused.revision == 2
    delay = timedelta(days=9, hours=3)
    resumed = resume(paused, expected_revision=2, now=at + delay)
    assert resumed.status == "active" and resumed.paused_at is None
    assert resumed.stages[0] == run.stages[0]
    assert resumed.stages[1].starts_at == run.stages[1].starts_at
    assert resumed.stages[1].ends_at - (at + delay) == run.stages[1].ends_at - at
    assert resumed.stages[2].starts_at == run.stages[2].starts_at + delay
    assert stage_at(resumed, at + delay).id == run.stages[1].id


def test_pause_at_stage_boundary_remains_contiguous_after_resume():
    run = journey()
    at = run.stages[1].starts_at
    paused = pause(run, expected_revision=1, now=at)
    resumed = resume(paused, expected_revision=2, now=at + timedelta(days=2))
    assert resumed.stages[0].ends_at == resumed.stages[1].starts_at
    assert stage_at(resumed, at + timedelta(days=2)).id == run.stages[1].id


def test_resume_cannot_replace_another_active_journey():
    run = journey()
    at = START + timedelta(hours=1)
    paused = pause(run, expected_revision=1, now=at)
    other = journey(run_id=uuid4(), now=at, existing=(paused,))
    with pytest.raises(JournalError, match="journal_active_conflict"):
        resume(paused, expected_revision=2, now=at, existing=(other,))


def test_paused_configuration_can_change_without_spending_its_remaining_time():
    run = journey()
    at = START + timedelta(days=2)
    paused = pause(run, expected_revision=1, now=at)
    definitions = tuple(stage.definition for stage in run.stages)
    adjusted = adjust_remaining_stages(
        paused,
        (changed(definitions[0], objective="Objetivo revisado"), *definitions[1:]),
        expected_revision=2,
        now=at + timedelta(days=20),
    )
    assert adjusted.status == "paused" and adjusted.paused_at == at
    assert adjusted.stages[0].ends_at == run.stages[0].ends_at
    resumed = resume(adjusted, expected_revision=3, now=at + timedelta(days=21))
    assert resumed.stages[0].ends_at == run.stages[0].ends_at + timedelta(days=21)


def test_text_only_edit_preserves_resumed_dates_across_dst():
    run = journey(now=datetime(2026, 3, 1, 5, tzinfo=UTC), timezone="America/New_York")
    at = run.started_at + timedelta(days=2)
    paused = pause(run, expected_revision=1, now=at)
    resumed = resume(paused, expected_revision=2, now=at + timedelta(days=8))
    definitions = tuple(stage.definition for stage in resumed.stages)
    adjusted = adjust_remaining_stages(
        resumed,
        definitions,
        expected_revision=3,
        now=resumed.updated_at,
        instructions="Cambiar sólo el foco, manteniendo las fechas.",
    )
    assert [stage.ends_at for stage in adjusted.stages] == [
        stage.ends_at for stage in resumed.stages
    ]


@pytest.mark.parametrize("action", [pause, close, advance])
def test_stale_revision_and_clock_regression_do_not_mutate_snapshot(action):
    run = journey()
    with pytest.raises(JournalError, match="journal_revision_conflict"):
        action(run, expected_revision=2, now=START + timedelta(hours=1))
    with pytest.raises(JournalError, match="journal_clock_regression"):
        action(run, expected_revision=1, now=START - timedelta(seconds=1))
    assert run.revision == 1


def test_two_admin_edits_require_the_new_revision():
    run = journey()
    now = START + timedelta(hours=1)
    definitions = tuple(stage.definition for stage in run.stages)
    adjusted = adjust_remaining_stages(
        run,
        definitions,
        expected_revision=1,
        now=now,
        instructions="Indicaciones nuevas",
    )
    with pytest.raises(JournalError, match="journal_revision_conflict"):
        adjust_remaining_stages(
            adjusted,
            definitions,
            expected_revision=1,
            now=now,
            purpose="Otro propósito",
        )
    assert adjusted.purpose == run.purpose


def test_adjustment_changes_only_remaining_stages_and_keeps_old_references():
    run = journey()
    current = run.stages[1]
    now = current.starts_at + timedelta(days=1)
    old_reference = question_context(OWNER, run, now).reference
    revised_definition = changed(
        current.definition, objective="Explorar situaciones concretas", duration_days=9
    )
    new_definition = changed(TEMPLATE.stages[0], key="support", name="Apoyos", duration_days=3)
    adjusted = adjust_remaining_stages(
        run,
        (revised_definition, run.stages[3].definition, new_definition),
        expected_revision=1,
        now=now,
    )
    assert adjusted.stages[0] == run.stages[0]
    assert adjusted.stages[1].id == current.id
    assert adjusted.stages[1].ends_at == current.ends_at + timedelta(days=2)
    assert adjusted.stages[2].id == run.stages[3].id
    assert adjusted.stages[3].definition.key == "support"
    assert run.stages[2].id not in {stage.id for stage in adjusted.stages}
    assert validate_entry_reference(OWNER, old_reference, run) == old_reference
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        validate_entry_reference(OWNER, old_reference, adjusted)
    assert run.stages[1].definition.objective != revised_definition.objective


def test_shortening_to_the_past_requires_explicit_advance():
    run = journey()
    definitions = tuple(stage.definition for stage in run.stages)
    now = START + timedelta(days=4)
    with pytest.raises(JournalError, match="journal_explicit_advance_required"):
        adjust_remaining_stages(
            run,
            (changed(definitions[0], duration_days=1), *definitions[1:]),
            expected_revision=1,
            now=now,
        )
    advanced = advance(run, expected_revision=1, now=now)
    assert stage_at(advanced, now).id == run.stages[1].id
    assert advanced.stages[0].ends_at == now
    assert run.stages[0].ends_at != now


def test_completed_stages_cannot_be_reintroduced_as_future_stages():
    run = journey()
    now = run.stages[1].starts_at
    with pytest.raises(JournalError, match="journal_completed_stage_immutable"):
        adjust_remaining_stages(
            run,
            (run.stages[1].definition, run.stages[0].definition),
            expected_revision=1,
            now=now,
        )


def test_last_explicit_advance_completes_without_an_integration_phase():
    run = journey()
    now = run.stages[-1].starts_at + timedelta(hours=1)
    completed = advance(run, expected_revision=1, now=now)
    assert completed.status == "completed" and completed.ended_at == now
    assert completed.stages[-1].ends_at == now
    assert isinstance(question_context(OWNER, completed, now), FreeQuestionContext)


def test_close_paused_and_reject_further_lifecycle_changes():
    run = journey()
    now = START + timedelta(hours=1)
    paused = pause(run, expected_revision=1, now=now)
    closed = close(paused, expected_revision=2, now=now + timedelta(hours=1))
    assert closed.status == "closed" and closed.paused_at is None
    with pytest.raises(JournalError, match="journal_not_paused"):
        resume(closed, expected_revision=3, now=now + timedelta(hours=2))
    with pytest.raises(JournalError, match="journal_already_ended"):
        close(closed, expected_revision=3, now=now + timedelta(hours=2))


def test_intention_revisions_invalidate_context_without_changing_history_or_admin_scope():
    run = journey()
    now = START + timedelta(hours=1)
    edited = edit_intention(run, "PRIVATE_INTENTION", expected_revision=1, now=now)
    old_context = question_context(OWNER, run, now)
    context = question_context(OWNER, edited, now)
    assert old_context.intention is None
    assert context.intention.text == "PRIVATE_INTENTION"
    assert context.reference.run_revision != old_context.reference.run_revision
    assert "PRIVATE_INTENTION" not in repr(context)
    assert "PRIVATE_INTENTION" not in repr(edited)
    assert "PRIVATE_INTENTION" not in administrative_run(edited, now).model_dump_json()
    cleared = edit_intention(edited, None, expected_revision=2, now=now)
    assert cleared.intention.revision == 2 and cleared.intention.text is None
    assert edited.intention.revision == 1 and edited.intention.text == "PRIVATE_INTENTION"


def test_public_projection_excludes_internal_instructions_and_owner():
    run = journey()
    view = public_run(run, START).model_dump(mode="json")
    assert view == FIXTURE["public_view"]
    assert "instructions" not in view and "owner_id" not in view
    assert all("instructions" not in stage for stage in view["stages"])
    assert run.instructions not in json.dumps(view)
    assert view["capture_reference"]["run_revision"] == 1
    context = question_context(OWNER, run, START)
    assert isinstance(context, JournalQuestionContext)
    assert context.instructions == run.instructions


def test_omitted_reference_is_free_and_response_context_is_authoritative():
    run = journey()
    reference = question_context(OWNER, run, START).reference
    assert validate_entry_reference(OWNER, None, run) == FIXTURE["legacy_reference"]
    response = ResponseJournalContext(reference=reference)
    assert validate_entry_reference(OWNER, None, run, response=response) == reference
    assert validate_entry_reference(OWNER, reference, run, response=response) == reference
    with pytest.raises(JournalError, match="journal_reference_conflict"):
        validate_entry_reference(OWNER, reference, run, response=ResponseJournalContext())
    other = reference.model_copy(update={"stage_id": run.stages[1].id})
    with pytest.raises(JournalError, match="journal_reference_conflict"):
        validate_entry_reference(OWNER, other, run, response=response)


def test_historical_capture_survives_stage_change_pause_and_close():
    archived = journey()
    reference = question_context(OWNER, archived, START).reference
    later = archived.stages[1].starts_at
    paused = pause(archived, expected_revision=1, now=later)
    closed = close(paused, expected_revision=2, now=later)
    assert closed.status == "closed"
    assert validate_entry_reference(OWNER, reference, archived) == reference
    assert reference.stage_id != archived.stages[1].id


@pytest.mark.parametrize("mismatch", ["owner", "run", "stage", "revision", "missing"])
def test_reference_validation_does_not_reveal_or_accept_foreign_resources(mismatch):
    run = journey()
    reference = question_context(OWNER, run, START).reference
    owner, archived = OWNER, run
    if mismatch == "owner":
        owner = uuid4()
    elif mismatch == "missing":
        archived = None
    else:
        field = {"run": "run_id", "stage": "stage_id", "revision": "run_revision"}[mismatch]
        reference = reference.model_copy(update={field: 2 if field == "run_revision" else uuid4()})
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        validate_entry_reference(owner, reference, archived)


def test_foreign_context_fails_instead_of_becoming_free():
    with pytest.raises(JournalError, match="journal_not_found"):
        question_context(uuid4(), journey(), START)
    assert isinstance(question_context(OWNER, None, START), FreeQuestionContext)


@pytest.mark.parametrize("days", [0, -1, True, "7", 366])
def test_duration_is_a_bounded_positive_integer(days):
    with pytest.raises(ValidationError):
        StageDefinition.model_validate({**TEMPLATE.stages[0].model_dump(), "duration_days": days})


@pytest.mark.parametrize("field", ["name", "purpose"])
def test_template_rejects_text_that_could_not_be_activated(field):
    with pytest.raises(ValidationError):
        JournalTemplate.model_validate({**TEMPLATE.model_dump(), field: " "})


def test_contracts_reject_extra_fields_duplicate_stages_and_sensitive_validation_repr():
    activation = ActivateRun.model_validate(FIXTURE["activation_request"])
    assert "owner_id" not in activation.model_dump()
    assert ChangeLifecycle.model_validate(FIXTURE["lifecycle_request"]).action == "pause"
    assert EditIntention.model_validate(FIXTURE["intention_request"]).expected_revision == 1
    request = AdjustRun(expected_revision=1, remaining_stages=TEMPLATE.stages)
    assert request.remaining_stages == TEMPLATE.stages
    with pytest.raises(ValidationError):
        EntryReference(run_id=uuid4(), stage_id=uuid4(), run_revision=1, owner_id=OWNER)
    with pytest.raises(ValidationError):
        JournalTemplate.model_validate(
            {
                **TEMPLATE.model_dump(),
                "stages": (TEMPLATE.stages[0],) * 2,
            }
        )
    with pytest.raises(ValidationError) as error:
        StageDefinition(key="valid", name="PRIVATE_TEXT", objective="", duration_days=7)
    assert "PRIVATE_TEXT" not in str(error.value)


def test_revision_history_records_action_and_origin_without_inventing_an_admin_identity():
    run = journey()
    now = START + timedelta(hours=1)
    assert (run.change, run.origin) == ("activation", "administration")
    edited = edit_intention(run, "Un propósito provisional", expected_revision=1, now=now)
    assert (edited.change, edited.origin) == ("intention", "user")
    paused = pause(edited, expected_revision=2, now=now)
    assert (paused.change, paused.origin) == ("pause", "administration")
    completed = reconcile(run, now=run.stages[-1].ends_at)
    assert (completed.change, completed.origin) == ("completion", "calendar")
    assert "actor_id" not in paused.model_dump()


@pytest.mark.parametrize(
    "mutation",
    [
        {"timezone": "Not/A_Zone"},
        {"paused_at": START},
        {"status": "completed"},
        {"updated_at": START - timedelta(seconds=1)},
        {"purpose": " "},
    ],
)
def test_run_rejects_incoherent_snapshots(mutation):
    with pytest.raises(ValidationError):
        JournalRun.model_validate({**journey().model_dump(), **mutation})


def test_naive_clock_and_invalid_timezone_fail_with_safe_errors():
    with pytest.raises(JournalError, match="journal_timezone_required"):
        journey(now=datetime(2026, 11, 2))
    with pytest.raises(JournalError, match="journal_invalid_timezone"):
        journey(timezone="Not/A_Zone")
    with pytest.raises(JournalError, match="journal_timezone_required"):
        stage_at(journey(), datetime(2026, 11, 2))


def test_naive_clock_fails_even_without_a_journal():
    with pytest.raises(JournalError, match="journal_timezone_required"):
        question_context(OWNER, None, datetime(2026, 11, 2))


def test_core_can_load_with_infrastructure_and_application_imports_blocked():
    source = """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'sqlalchemy', 'taskiq', 'openai'} or any(
            fullname == name or fullname.startswith(name + '.')
            for name in ('src.adapters', 'src.bootstrap', 'src.use_cases')
        ):
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from src.core.journals import contracts, rules
"""
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True, text=True)


def test_short_description_is_copied_without_changing_legacy_snapshots_or_catalog_goals():
    from src.core.journals.preparation_catalog import (
        PREPARATION_TEMPLATE_V2,
        PREPARATION_TEMPLATE_V3,
    )
    from src.core.journals.rules import activate

    assert "short_description" not in PREPARATION_TEMPLATE_V2.model_dump(mode="json")
    assert PREPARATION_TEMPLATE_V3.catalogs == PREPARATION_TEMPLATE_V2.catalogs
    run = activate(
        PREPARATION_TEMPLATE_V3, run_id=uuid4(), owner=uuid4(), timezone="UTC", now=START
    )
    assert run.short_description == "Dale forma a tu intención."
    assert public_run(run, START).short_description == run.short_description
    assert journey().short_description is None
    assert "short_description" not in journey().model_dump(mode="json")


@pytest.mark.parametrize("text", ["", "  Idea", "Idea ", "Idea\nNueva", "x" * 161])
def test_short_description_rejects_invalid_presentation_text(text):
    from src.core.journals.models import JournalTemplate
    from src.core.journals.templates import PREPARATION_TEMPLATE

    payload = PREPARATION_TEMPLATE.model_dump()
    with pytest.raises(ValidationError):
        JournalTemplate.model_validate({**payload, "short_description": text})
