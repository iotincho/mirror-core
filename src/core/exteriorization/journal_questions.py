"""Context identities and curated journal packages, using the existing topic policy."""

import hashlib
from typing import Literal
from uuid import uuid5

from pydantic import Field

from src.core.exteriorization.contracts import Trigger
from src.core.exteriorization.personalization import (
    PreparationConfiguration,
    PreparationSnapshot,
    encoded_input,
)
from src.core.exteriorization.question_contracts import (
    InvitationQuestion,
    InvitationQuestionSet,
    QuestionGroup,
)
from src.core.exteriorization.question_policy import (
    QuestionSelectionContext,
    RankedQuestionGroup,
    TopicState,
    select_question_groups,
)
from src.core.journals.contracts import EntryReference


class JournalPreparationConfiguration(PreparationConfiguration):
    version: Literal["daily-preparation-v2"] = "daily-preparation-v2"
    prompt_version: Literal["journal-proposals-v1"] = "journal-proposals-v1"
    journal_reference: EntryReference


class JournalPreparationSnapshot(PreparationSnapshot):
    journal_reference: EntryReference
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def context_key(reference=None):
    if reference is None:
        return "free"
    return f"journal:{reference.run_id}:{reference.stage_id}:{reference.run_revision}"


def context_hash(context):
    return hashlib.sha256(
        encoded_input(
            context.model_dump(
                mode="json",
                exclude={"owner_id"},
            )
        ).encode()
    ).hexdigest()


def journal_topic_id(owner, key):
    return uuid5(owner, f"journal-catalog-topic-v1:{key}")


def journal_topics(owner, context):
    return (
        tuple(
            (journal_topic_id(owner, prompt.key), f"journal:{prompt.key}")
            for prompt in context.catalog.prompts
        )
        if context.catalog
        else ()
    )


def build_journal_questions(identifier, owner, context, now, facts, policy, history=()):
    if context.catalog is None:
        return None
    by_topic = {fact.topic.id: fact for fact in facts}
    recent = {}
    for position, item in enumerate(history[:7]):
        recent.setdefault(item.candidate_id, position)
    candidates, by_group, bindings = [], {}, {}
    order = sorted(
        context.catalog.prompts, key=lambda prompt: -recent.get(f"journal:{prompt.key}", 99)
    )
    for prompt in order:
        topic = journal_topic_id(owner, prompt.key)
        fact = by_topic.get(topic)
        group_id = uuid5(identifier, f"journal-catalog-group-v1:{prompt.key}")
        group = QuestionGroup(
            id=group_id,
            source="generic",
            questions=tuple(
                InvitationQuestion(
                    id=uuid5(group_id, depth), depth=depth, text=getattr(prompt, depth)
                )
                for depth in ("gentle", "middle", "deep")
            ),
        )
        candidates.append(
            RankedQuestionGroup(
                group=group,
                topic=fact.topic
                if fact
                else TopicState(
                    id=topic,
                    user_id=owner,
                    scope="catalog",
                ),
                evidence_valid=True,
                last_shown_at=fact.last_shown_at if fact else None,
                last_shown_answered=fact.answered if fact else False,
            )
        )
        by_group[group_id], bindings[group_id] = (prompt, group), topic
    selected = select_question_groups(
        QuestionSelectionContext(user_id=owner, now=now), tuple(candidates), policy
    )
    if not selected.group_ids:
        return None
    prompt = by_group[selected.group_ids[0]][0]
    groups = tuple(by_group[key][1] for key in selected.group_ids)
    return (
        Trigger(
            source="generic",
            candidate_id=f"journal:{prompt.key}",
            category="journal",
            question=groups[0].questions[1].text,
            engine_version="journal-curated-v1",
            catalog_version="journal-catalog-v1",
        ),
        InvitationQuestionSet(
            id=identifier,
            question=groups[0].questions[1].text,
            default_question_id=groups[0].questions[1].id,
            question_groups=groups,
        ),
        tuple((key, bindings[key]) for key in selected.group_ids),
    )
