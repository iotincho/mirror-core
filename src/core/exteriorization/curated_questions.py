"""Curated depth variants and owner-scoped identities, without persistence or I/O."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from src.core.exteriorization.catalog import CATALOG
from src.core.exteriorization.engine import select_trigger
from src.core.exteriorization.question_contracts import (
    InvitationQuestion,
    InvitationQuestionSet,
    QuestionGroup,
)
from src.core.exteriorization.question_policy import (
    QuestionPolicy,
    QuestionSelectionContext,
    RankedQuestionGroup,
    TopicState,
    select_question_groups,
)

# Middle questions retain the existing catalog's exact text.
VARIANTS = (
    ("¿Con qué momento de hoy te quedás?", "¿Qué de tu día te gustaría entender mejor?"),
    ("¿Qué pequeño detalle de hoy recordás?", "¿Qué hizo importante ese momento para vos?"),
    ("¿Hubo algo distinto en tu día?", "¿Qué te dejó pensando esa sorpresa?"),
    ("¿Hubo un ratito agradable hoy?", "¿Qué necesitabas de eso que te hizo bien?"),
    ("¿Qué cosa pequeña disfrutaste?", "¿Qué lugar te gustaría darle a eso que disfrutás?"),
    ("¿Qué imagen de hoy te gustaría guardar?", "¿Qué dice de vos eso que querés recordar?"),
    ("¿Hubo un momento que preferirías dejar atrás?", "¿Qué te habría ayudado en ese momento?"),
    ("¿Qué parte del día se sintió más pesada?", "¿Qué necesitaste hoy y te costó encontrar?"),
    ("¿Hay algo que quieras sacar de tu cabeza?", "¿Qué te gustaría poder expresar sobre eso?"),
    ("¿Qué palabra describe este momento?", "¿Qué de eso que te ocupa merece más espacio?"),
    ("¿Hay alguna idea que quieras dejar anotada?", "¿Qué te mueve de esa idea que apareció?"),
    ("¿Qué detalle de tu día te dio curiosidad?", "¿Qué pregunta te quedó abierta sobre tu día?"),
)


def catalog_topic_id(owner: UUID, candidate_id: str) -> UUID:
    return uuid5(owner, f"curated-topic-v1:{candidate_id}")


@dataclass(frozen=True)
class CatalogTopicFact:
    topic: TopicState
    last_shown_at: datetime | None = None
    answered: bool = False


def catalog_topics(owner):
    return tuple(
        (catalog_topic_id(owner, item.candidate_id), item.candidate_id) for item in CATALOG
    )


def build_curated_questions(identifier, owner, context, facts=(), *, policy=None):
    """Retain v1 recency ordering, then apply explicit v2 eligibility rules."""
    policy = policy or QuestionPolicy()
    primary = select_trigger(context)
    recent = {item.candidate_id for item in context.history[:7]}
    order = sorted(
        CATALOG,
        key=lambda item: (
            item.candidate_id != primary.candidate_id,
            item.candidate_id in recent,
            item.category == primary.category,
        ),
    )
    by_topic = {fact.topic.id: fact for fact in facts}
    groups = {}
    ranked = []
    for item in order:
        gentle, deep = VARIANTS[CATALOG.index(item)]
        group_id = uuid5(identifier, f"curated-group-v2:{item.candidate_id}")
        group = QuestionGroup(
            id=group_id,
            source="generic",
            questions=tuple(
                InvitationQuestion(id=uuid5(group_id, depth), depth=depth, text=text)
                for depth, text in (("gentle", gentle), ("middle", item.question), ("deep", deep))
            ),
        )
        topic_id = catalog_topic_id(owner, item.candidate_id)
        fact = by_topic.get(topic_id)
        ranked.append(
            RankedQuestionGroup(
                group=group,
                topic=fact.topic
                if fact
                else TopicState(id=topic_id, user_id=owner, scope="catalog"),
                evidence_valid=True,
                last_shown_at=fact.last_shown_at if fact else None,
                last_shown_answered=fact.answered if fact else False,
            )
        )
        groups[group_id] = item, group
    result = select_question_groups(
        QuestionSelectionContext(user_id=owner, now=context.now), tuple(ranked), policy
    )
    if not result.group_ids:
        return None
    item = groups[result.group_ids[0]][0].model_copy(
        update={
            "engine_version": "generic-v2",
            "catalog_version": "2",
        }
    )
    selected = tuple(groups[key][1] for key in result.group_ids)
    package = InvitationQuestionSet(
        id=identifier,
        question=item.question,
        default_question_id=selected[0].questions[1].id,
        question_groups=selected,
    )
    bindings = tuple(
        (group_id, catalog_topic_id(owner, groups[group_id][0].candidate_id))
        for group_id in result.group_ids
    )
    return item, package, bindings
