"""Ephemeral synthetic ports; no user directories, SQL connections or provider calls."""

from uuid import UUID, uuid5

from src.core.documents.ports import DocumentNotFoundError
from src.core.domain.documents import Document
from src.core.exteriorization.contracts import EngineContext
from src.core.exteriorization.curated_questions import (
    CatalogTopicFact,
    build_curated_questions,
    catalog_topics,
)
from src.core.exteriorization.personalization import PersonalQuestionFact, proposal_topic_id
from src.core.exteriorization.question_policy import TopicState

EVALUATION_OWNER = UUID("95f73f60-c86a-41ca-a950-f5a62a061b0e")


class SyntheticQuestionRuntime:
    def __init__(self, case, configuration):
        self.case, self.configuration = case, configuration
        self.owner = EVALUATION_OWNER
        self.identifier = uuid5(self.owner, case.id)
        self.documents_by_id = {
            note.id: Document(
                id=note.id,
                content=note.content,
                authored_at=note.authored_at,
                created_at=note.accepted_at,
                source="synthetic-evaluation",
                metadata={},
            )
            for note in case.notes
        }
        self.states = {item.topic.id: item.topic for item in case.final_topics or case.topics}
        self.catalog = tuple(
            CatalogTopicFact(TopicState(id=identifier, user_id=self.owner, scope="catalog"))
            for identifier, _ in catalog_topics(self.owner)
        )
        self.prepared = None
        self.decision = None

    async def documents(self, owner):
        if owner != self.owner:
            raise ValueError("evaluation_owner_mismatch")
        return self

    async def get(self, identifier):
        if identifier not in self.documents_by_id:
            raise DocumentNotFoundError()
        return self.documents_by_id[identifier]

    async def inventory(self, owner, now):
        if owner != self.owner:
            raise ValueError("evaluation_owner_mismatch")
        history = []
        for previous in self.case.history:
            identifier = uuid5(self.identifier, str(previous.topic_id))
            question = (
                self.case.reference.proposals[0].questions.middle
                if self.case.reference.proposals
                else "¿Qué te gustaría contar de ese tema?"
            )
            responses = (
                [str(self.case.notes[0].id)] if previous.answered and self.case.notes else []
            )
            history.append(
                dict(
                    id=str(identifier),
                    source="personalized",
                    question=question,
                    created_at=previous.shown_at.isoformat(),
                    responses=responses,
                    questions=[
                        dict(
                            id=str(uuid5(identifier, "middle")),
                            text=question,
                            depth="middle",
                            shown=True,
                            responses=responses,
                            feedback=None,
                        )
                    ],
                )
            )
        return [(note.id, note.accepted_at) for note in self.case.notes], history, self.case.topics

    def curated(self):
        return build_curated_questions(
            self.identifier,
            self.owner,
            EngineContext(now=self.case.now, timezone="UTC"),
            self.catalog,
            policy=self.configuration.policy,
        )

    async def prepared_questions(self, *_):
        return self.prepared

    async def guard_question_sources(self, *_):
        return True

    async def personal_question_facts(self, owner, proposals, *, rest_days=7):
        history = {item.topic_id: item for item in self.case.history}
        result = []
        for proposal in proposals:
            identifier = proposal_topic_id(owner, proposal)
            state = self.states.get(identifier) or TopicState(
                id=identifier, user_id=owner, scope="personal"
            )
            previous = history.get(identifier)
            result.append(
                PersonalQuestionFact(
                    state,
                    previous.shown_at if previous else None,
                    previous.answered if previous else False,
                    previous.followups if previous else 0,
                )
            )
        return result

    async def catalog_state(self, *_):
        return self.catalog

    async def personalized_initials(self, *_):
        return self.case.consecutive_personalized

    async def save_topic(self, topic):
        self.states[topic.id] = topic

    async def record_question_decision(self, _, code):
        self.decision = code
