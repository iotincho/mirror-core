"""Explicit topic pause and undo use owner-scoped, replay-safe receipts."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.adapters.access.api.public.errors import invitation_error_handler
from src.adapters.access.api.public.invitations.routes import build_router
from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.question_contracts import InvitationQuestionSet
from src.core.exteriorization.question_policy import TopicState
from src.use_cases.exteriorization.record_activity import RecordInvitationActivity


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Repository:
    def __init__(self):
        data = json.loads(
            (Path(__file__).parent / "fixtures/daily_questions_v2_contract.json").read_text()
        )
        self.owner = UUID(data["user_id"])
        questions = InvitationQuestionSet.model_validate(data["question_set"])
        self.invitation_record = SimpleNamespace(
            id=questions.id, questions=questions, kind="scheduled", question_policy=None
        )
        self.topic = TopicState(id=uuid4(), user_id=self.owner, scope="personal")
        self.receipts = {}
        self.feedback = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def preference(self, owner):
        if owner != self.owner:
            raise InvitationError("invitation_not_found")

    async def invitation(self, owner, identifier):
        if owner != self.owner or identifier != self.invitation_record.id:
            raise InvitationError("invitation_not_found")
        return self.invitation_record

    async def now(self):
        return datetime(2026, 10, 29, 12, tzinfo=UTC)

    async def feedback_topic(self, owner, invitation_id, question_id):
        return self.topic

    async def save_topic(self, topic):
        self.topic = topic

    async def activity_receipt(self, owner, operation, key, request_hash):
        previous = self.receipts.get((owner, operation, key))
        if previous and previous[0] != request_hash:
            raise InvitationError("idempotency_conflict")
        return previous[1] if previous else None

    async def activity_receipt_by_id(self, owner, operation, identifier):
        return next(
            (
                body
                for (user, op, _), (_, body, receipt_id) in self.receipts.items()
                if user == owner and op == operation and receipt_id == identifier
            ),
            None,
        )

    async def save_activity_receipt(self, owner, operation, key, request_hash, body, identifier):
        self.receipts[(owner, operation, key)] = (request_hash, body, identifier)

    async def append_feedback(self, *args):
        self.feedback.append(args)


@pytest.mark.anyio
async def test_pause_and_undo_are_replay_safe_and_restore_the_previous_state():
    repo = Repository()
    service = RecordInvitationActivity(repo)
    question_id = repo.invitation_record.questions.default_question_id
    key = uuid4()
    first = await service.pause_topic(repo.owner, repo.invitation_record.id, question_id, key)
    assert repo.topic.status == "paused"
    assert (
        await service.pause_topic(repo.owner, repo.invitation_record.id, question_id, key) == first
    )
    assert len(repo.feedback) == 1
    other_question = repo.invitation_record.questions.question_groups[0].questions[0].id
    with pytest.raises(InvitationError, match="idempotency_conflict"):
        await service.pause_topic(repo.owner, repo.invitation_record.id, other_question, key)
    undo_key = uuid4()
    result = await service.undo_topic_pause(
        repo.owner, repo.invitation_record.id, UUID(first["id"]), undo_key
    )
    assert repo.topic.status == "open"
    assert repo.topic.last_feedback_sequence == 2
    assert (
        await service.undo_topic_pause(
            repo.owner, repo.invitation_record.id, UUID(first["id"]), undo_key
        )
        == result
    )
    with pytest.raises(InvitationError, match="topic_pause_superseded"):
        await service.undo_topic_pause(
            repo.owner, repo.invitation_record.id, UUID(first["id"]), uuid4()
        )


@pytest.mark.anyio
async def test_undo_never_removes_a_later_stronger_restriction_or_another_owners_pause():
    repo = Repository()
    service = RecordInvitationActivity(repo)
    question_id = repo.invitation_record.questions.default_question_id
    pause = await service.pause_topic(repo.owner, repo.invitation_record.id, question_id, uuid4())
    repo.topic = repo.topic.model_copy(
        update={"status": "closed", "paused_until": None, "last_feedback_sequence": 2}
    )
    with pytest.raises(InvitationError, match="topic_pause_superseded"):
        await service.undo_topic_pause(
            repo.owner, repo.invitation_record.id, UUID(pause["id"]), uuid4()
        )
    assert repo.topic.status == "closed"
    with pytest.raises(InvitationError, match="invitation_not_found"):
        await service.undo_topic_pause(
            uuid4(), repo.invitation_record.id, UUID(pause["id"]), uuid4()
        )


@pytest.mark.anyio
async def test_undo_restores_an_earlier_pause_instead_of_opening_the_topic():
    repo = Repository()
    service = RecordInvitationActivity(repo)
    question_id = repo.invitation_record.questions.default_question_id
    await service.pause_topic(repo.owner, repo.invitation_record.id, question_id, uuid4())
    original_pause = repo.topic
    second = await service.pause_topic(repo.owner, repo.invitation_record.id, question_id, uuid4())
    await service.undo_topic_pause(
        repo.owner, repo.invitation_record.id, UUID(second["id"]), uuid4()
    )
    assert repo.topic.status == "paused"
    assert repo.topic.paused_until == original_pause.paused_until
    assert repo.topic.last_feedback_sequence == 3


@pytest.mark.anyio
async def test_http_hides_internal_topic_state_and_validates_question_ownership():
    repo = Repository()
    service = SimpleNamespace(activity=RecordInvitationActivity(repo))
    app = FastAPI()
    app.add_exception_handler(InvitationError, invitation_error_handler)

    async def user():
        return SimpleNamespace(id=repo.owner)

    async def invitations():
        return service

    async def same_origin():
        return None

    app.include_router(build_router(user, invitations, same_origin))
    path = f"/exteriorization/invitations/{repo.invitation_record.id}/topic-pause"
    question_id = repo.invitation_record.questions.default_question_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        result = await client.post(
            path,
            json={"invitation_question_id": str(question_id)},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert result.status_code == 200, result.text
        assert set(result.json()) == {
            "id",
            "invitation_id",
            "invitation_question_id",
            "paused_until",
        }
        invalid = await client.post(
            path,
            json={"invitation_question_id": str(uuid4())},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert invalid.status_code == 404
        undone = await client.post(
            f"{path}/{result.json()['id']}/undo", headers={"Idempotency-Key": str(uuid4())}
        )
        assert undone.status_code == 200
        assert repo.topic.status == "open"
