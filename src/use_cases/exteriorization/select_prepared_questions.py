"""Separate versioned selection artifact and last-moment eligibility checks."""

from uuid import UUID

from src.core.documents.original_access import OriginalStorageUnavailable
from src.core.documents.ports import DocumentNotFoundError
from src.core.exteriorization.contracts import Trigger
from src.core.exteriorization.personalization import (
    PreparationSnapshot,
    PreparedQuestions,
    content_hash,
    proposal_group,
    proposal_order,
    proposal_topic_id,
    validate_proposals,
)
from src.core.exteriorization.question_contracts import InvitationQuestionSet
from src.core.exteriorization.question_policy import (
    QuestionSelectionContext,
    RankedQuestionGroup,
    TopicReopeningEvidence,
    reopen_topic,
    select_question_groups,
)


def select_proposals(identifier, owner, snapshot, proposals):
    return {
        "version": "daily-selection-v1",
        "ordered_topics": [
            str(proposal_topic_id(owner, proposal))
            for proposal in proposal_order(proposals.proposals, snapshot.sources)
            if proposal.intent in {"explore", "reopen"}
        ],
    }


class SelectPreparedQuestions:
    def __init__(self, originals):
        self.originals = originals

    async def execute(
        self, transaction, preference, due, now, curated, policy, *, preference_version
    ):
        prepared = await transaction.prepared_questions(preference.user_id, due, preference_version)
        if prepared is None:
            return curated
        identifier, raw_snapshot, raw_proposals, selection, configuration = prepared
        try:
            snapshot = PreparationSnapshot.model_validate(raw_snapshot)
            proposals = validate_proposals(raw_proposals, snapshot)
        except ValueError:
            await transaction.record_question_decision(identifier, "invalid_artifact")
            return curated
        sources = {source.document_id: source for source in snapshot.sources}
        ids = [source.document_id for source in snapshot.sources]
        if not await transaction.guard_question_sources(preference.user_id, ids):
            await transaction.record_question_decision(identifier, "source_busy")
            return curated
        try:
            originals = await self.originals.documents(preference.user_id)
        except (OriginalStorageUnavailable, OSError):
            await transaction.record_question_decision(identifier, "original_storage_unavailable")
            return curated
        valid = set()
        for source in snapshot.sources:
            try:
                document = await originals.get(source.document_id)
                if content_hash(document) == source.sha256:
                    valid.add(source.document_id)
            except (DocumentNotFoundError, OSError, ValueError):
                pass
        eligible = [
            proposal
            for proposal in proposals.proposals
            if proposal.intent in {"explore", "reopen"}
            and all(e.document_id in valid for e in proposal.evidence)
        ]
        facts = await transaction.personal_question_facts(
            preference.user_id, eligible, rest_days=policy.rest_days
        )
        by_topic = {fact.topic.id: fact for fact in facts}
        candidates, bindings, changed, provenance = [], {}, {}, {}
        ordered = {UUID(key): index for index, key in enumerate(selection["ordered_topics"])}
        for proposal in sorted(
            eligible, key=lambda item: ordered.get(proposal_topic_id(preference.user_id, item), 99)
        ):
            topic_id = proposal_topic_id(preference.user_id, proposal)
            fact = by_topic[topic_id]
            topic = fact.topic
            if proposal.intent == "reopen" and proposal.basis == "explicit":
                for evidence in proposal.evidence:
                    source = sources[evidence.document_id]
                    topic = reopen_topic(
                        topic,
                        TopicReopeningEvidence(
                            user_id=preference.user_id,
                            topic_id=topic_id,
                            document_id=source.document_id,
                            authored_at=source.authored_at,
                            accepted_at=source.accepted_at,
                            association="confirmed",
                            intent="explicit",
                            original_available=True,
                        ),
                        now=now,
                    )
            group = proposal_group(identifier, preference.user_id, proposal)
            provenance[str(group.id)] = dict(
                source="personalized",
                preparation_id=str(identifier),
                topic_id=str(topic_id),
                configuration=configuration,
                policy=policy.model_dump(mode="json"),
                evidence=[
                    {**e.model_dump(mode="json"), "sha256": sources[e.document_id].sha256}
                    for e in proposal.evidence
                ],
            )
            candidates.append(
                RankedQuestionGroup(
                    group=group,
                    topic=topic,
                    evidence_valid=True,
                    last_shown_at=fact.last_shown_at,
                    last_shown_answered=fact.answered,
                    followups_since_rest=fact.followups,
                )
            )
            bindings[group.id], changed[topic.id] = topic.id, topic
        trigger, package, generic_bindings = curated
        generic_facts = await transaction.catalog_state(preference.user_id, ())
        by_catalog = {fact.topic.id: fact for fact in generic_facts}
        for group in package.question_groups:
            topic_id = dict(generic_bindings)[group.id]
            fact = by_catalog[topic_id]
            candidates.append(
                RankedQuestionGroup(
                    group=group,
                    topic=fact.topic,
                    evidence_valid=True,
                    last_shown_at=fact.last_shown_at,
                    last_shown_answered=fact.answered,
                )
            )
            bindings[group.id] = topic_id
        result = select_question_groups(
            QuestionSelectionContext(
                user_id=preference.user_id,
                now=now,
                consecutive_personalized_initials=await transaction.personalized_initials(
                    preference.user_id
                ),
            ),
            tuple(candidates),
            policy,
        )
        if not result.group_ids:
            return curated
        by_group = {item.group.id: item.group for item in candidates}
        selected = tuple(by_group[key] for key in result.group_ids)
        for group in selected:
            topic = changed.get(bindings[group.id])
            if topic:
                await transaction.save_topic(topic)
        initial = selected[0]
        if initial.source == "personalized":
            trigger = Trigger(
                source="personalized",
                candidate_id=f"personal:{bindings[initial.id]}",
                category="personal",
                question=initial.questions[1].text,
                engine_version="personal-v1",
                catalog_version="2",
            )
        await transaction.record_question_decision(
            identifier,
            "prepared"
            if any(group.source == "personalized" for group in selected)
            else "no_eligible_personal",
        )
        return PreparedQuestions(
            trigger,
            InvitationQuestionSet(
                id=package.id,
                question=initial.questions[1].text,
                default_question_id=initial.questions[1].id,
                question_groups=selected,
            ),
            tuple((key, bindings[key]) for key in result.group_ids),
            {
                str(group.id): provenance[str(group.id)]
                for group in selected
                if str(group.id) in provenance
            },
        )
