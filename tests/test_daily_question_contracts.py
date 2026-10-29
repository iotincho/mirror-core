"""Synthetic stage-1 contracts and policies; no runtime, storage or provider calls."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.core.exteriorization.question_contracts import (
    InvitationFeedbackChoice,
    InvitationInteractions,
    InvitationQuestionSet,
    InvitationResponseReference,
    legacy_question_set,
    resolve_response_question,
)
from src.core.exteriorization.question_policy import (
    QuestionPolicy,
    QuestionSelectionContext,
    RankedQuestionGroup,
    TopicFeedback,
    TopicReopeningEvidence,
    TopicState,
    apply_topic_feedback,
    reopen_topic,
    select_question_groups,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/daily_questions_v2_contract.json").read_text()
)
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
POLICY = QuestionPolicy()


def test_public_example_is_immutable_and_does_not_expose_private_context():
    package = InvitationQuestionSet.model_validate(FIXTURE["question_set"])
    assert package.model_dump(mode="json") == FIXTURE["question_set"]
    with pytest.raises(ValidationError):
        package.question_groups[0].questions[0].text = "changed"
    assert package.question not in repr(package)
    data = copy.deepcopy(FIXTURE["question_set"])
    data["question_groups"][0]["topic_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        InvitationQuestionSet.model_validate(data)


@pytest.mark.parametrize("defect", ["default", "duplicate_id", "depths", "text", "size"])
def test_package_rejects_inconsistent_history_or_incomplete_depths(defect):
    data = copy.deepcopy(FIXTURE["question_set"])
    group = data["question_groups"][0]
    if defect == "default":
        data["default_question_id"] = group["questions"][0]["id"]
    elif defect == "duplicate_id":
        data["question_groups"][1]["questions"][0]["id"] = group["questions"][0]["id"]
    elif defect == "depths":
        group["questions"][2]["depth"] = "middle"
    elif defect == "text":
        data["question"] = "A different push question"
    else:
        group["questions"][0]["text"] = "x" * 241
    with pytest.raises(ValidationError):
        InvitationQuestionSet.model_validate(data)


def test_legacy_projection_is_stable_and_keeps_the_exact_question():
    old = FIXTURE["legacy"]
    package = legacy_question_set(UUID(old["invitation_id"]), old["question"])
    assert package == legacy_question_set(UUID(old["invitation_id"]), old["question"])
    assert package.question == old["question"]
    assert len(package.question_groups) == 1
    question = package.question_groups[0].questions[0]
    assert question.depth is None
    assert package.question_groups[0].layout == "legacy"
    reference = InvitationResponseReference(invitation_id=package.id)
    assert resolve_response_question(package, reference) == question


def test_response_identifies_the_chosen_variant_and_old_clients_keep_default():
    package = InvitationQuestionSet.model_validate(FIXTURE["question_set"])
    chosen = package.question_groups[0].questions[2]
    old = InvitationResponseReference(invitation_id=package.id)
    new = InvitationResponseReference(invitation_id=package.id, invitation_question_id=chosen.id)
    assert resolve_response_question(package, old).id == package.default_question_id
    assert resolve_response_question(package, new) == chosen
    with pytest.raises(ValueError, match="invitation_question_not_found"):
        resolve_response_question(
            package,
            InvitationResponseReference(invitation_id=package.id, invitation_question_id=uuid4()),
        )
    with pytest.raises(ValueError, match="invitation_not_found"):
        resolve_response_question(package, InvitationResponseReference(invitation_id=uuid4()))
    with pytest.raises(ValidationError):
        InvitationResponseReference(invitation_question_id=chosen.id)


def test_feedback_and_interactions_accept_only_their_public_fields():
    choice = InvitationFeedbackChoice.model_validate(FIXTURE["feedback_input"])
    assert choice.value == "closed"
    with pytest.raises(ValidationError):
        InvitationFeedbackChoice.model_validate({**FIXTURE["feedback_input"], "user_id": uuid4()})
    data = copy.deepcopy(FIXTURE["interactions_input"])
    assert len(InvitationInteractions.model_validate(data).events) == 1
    data["events"][0]["received_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        InvitationInteractions.model_validate(data)
    data = FIXTURE["interactions_input"]["events"][0]
    with pytest.raises(ValidationError):
        InvitationInteractions(events=(data, data))


@pytest.mark.parametrize("case", FIXTURE["policy_cases"], ids=lambda case: case["name"])
def test_selection_examples_respect_boundaries_and_keep_variety(case):
    data = copy.deepcopy(FIXTURE["ranked_candidates"])
    for index, changes in case.get("overrides", {}).items():
        candidate = data[int(index)]
        changes = changes.copy()
        candidate["topic"].update(changes.pop("topic", {}))
        candidate.update(changes)
    indices = case.get("candidate_indices", range(len(data)))
    ranked = tuple(RankedQuestionGroup.model_validate(data[index]) for index in indices)
    context = QuestionSelectionContext(
        user_id=FIXTURE["user_id"],
        now=case.get("now", NOW),
        consecutive_personalized_initials=case.get("consecutive_personalized_initials", 0),
    )
    before = tuple(item.model_dump_json() for item in ranked)
    result = select_question_groups(context, ranked, POLICY)
    assert result.group_ids == tuple(
        UUID(data[index]["group"]["id"]) for index in case["expected_groups"]
    )
    assert result.requires_catalog == case.get("requires_catalog", False)
    assert {item.group_id: item.code for item in result.excluded} == {
        UUID(data[int(index)]["group"]["id"]): code
        for index, code in case.get("excluded", {}).items()
    }
    assert tuple(item.model_dump_json() for item in ranked) == before


def topic():
    return TopicState.model_validate(FIXTURE["ranked_candidates"][0]["topic"])


def feedback(subject, value, sequence=1):
    return TopicFeedback(
        user_id=subject.user_id,
        topic_id=subject.id,
        value=value,
        sequence=sequence,
        received_at=NOW,
    )


@pytest.mark.parametrize("value", ["helpful", "unrelated", "not_now", "closed"])
def test_positive_or_weaker_feedback_never_removes_explicit_rejection(value):
    subject = topic()
    rejected = apply_topic_feedback(subject, feedback(subject, "do_not_prompt"), POLICY)
    result = apply_topic_feedback(rejected, feedback(subject, value, 2), POLICY)
    assert result.status == "do_not_prompt"
    assert result.restricted_at == rejected.restricted_at
    assert result.last_feedback_sequence == 2


def test_feedback_replay_and_late_sequence_do_not_repeat_or_reverse_effects():
    subject = topic()
    event = feedback(subject, "closed", 2)
    closed = apply_topic_feedback(subject, event, POLICY)
    assert apply_topic_feedback(closed, event, POLICY) == closed
    assert apply_topic_feedback(closed, feedback(subject, "not_now"), POLICY) == closed


def test_feedback_rest_is_timed_while_closure_has_no_deadline():
    subject = topic()
    paused = apply_topic_feedback(subject, feedback(subject, "not_now"), POLICY)
    assert paused.status == "paused"
    assert paused.paused_until == datetime(2026, 11, 5, 12, tzinfo=UTC)
    closed = apply_topic_feedback(paused, feedback(subject, "closed", 2), POLICY)
    assert closed.status == "closed"
    assert closed.paused_until is None


def reopening_evidence(subject, **changes):
    return TopicReopeningEvidence.model_validate(
        {
            "user_id": subject.user_id,
            "topic_id": subject.id,
            "document_id": uuid4(),
            "authored_at": "2026-10-30T10:00:00Z",
            "accepted_at": "2026-10-30T11:00:00Z",
            "association": "confirmed",
            "intent": "explicit",
            "original_available": True,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "mention"},
        {"intent": "rejected"},
        {"intent": "uncertain"},
        {"association": "uncertain"},
        {"original_available": False},
        {"authored_at": "2026-01-01T00:00:00Z"},
        {"accepted_at": "2026-10-28T00:00:00Z"},
        {"authored_at": "2027-01-01T00:00:00Z"},
    ],
)
def test_mentions_old_imports_or_invalid_evidence_do_not_reopen(changes):
    subject = topic()
    closed = apply_topic_feedback(subject, feedback(subject, "closed"), POLICY)
    result = reopen_topic(
        closed,
        reopening_evidence(subject, **changes),
        now=datetime(2026, 10, 30, 12, tzinfo=UTC),
    )
    assert result == closed


@pytest.mark.parametrize("value", ["not_now", "closed", "do_not_prompt"])
def test_new_explicit_intention_reopens_with_traceable_evidence(value):
    subject = topic()
    restricted = apply_topic_feedback(subject, feedback(subject, value), POLICY)
    evidence = reopening_evidence(subject)
    result = reopen_topic(restricted, evidence, now=datetime(2026, 10, 30, 12, tzinfo=UTC))
    assert result.status == "open"
    assert result.reopened_by_document_id == evidence.document_id
    assert result.restricted_at == restricted.restricted_at
    assert result.last_feedback_sequence == restricted.last_feedback_sequence
    assert result.paused_until is None


def test_policy_rejects_cross_account_context_and_effects():
    subject = topic()
    foreign = uuid4()
    with pytest.raises(ValueError, match="feedback_topic_owner_mismatch"):
        apply_topic_feedback(
            subject, feedback(subject, "closed").model_copy(update={"user_id": foreign}), POLICY
        )
    with pytest.raises(ValueError, match="reopening_topic_owner_mismatch"):
        reopen_topic(subject, reopening_evidence(subject, user_id=foreign), now=NOW)
    candidates = tuple(
        RankedQuestionGroup.model_validate(item) for item in FIXTURE["ranked_candidates"]
    )
    with pytest.raises(ValueError, match="candidate_owner_mismatch"):
        select_question_groups(
            QuestionSelectionContext(user_id=foreign, now=NOW), candidates, POLICY
        )
