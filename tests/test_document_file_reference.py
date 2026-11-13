"""File uploads use the same invitation and journal contract as text documents."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.adapters.access.api.public.routes.processing import build_router
from src.core.exteriorization.models import InvitationError
from src.core.journals.contracts import EntryReference
from src.use_cases.processing.public import PublicProcessing


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_file_submission_passes_association_through_the_existing_document_flow():
    submissions = SimpleNamespace(execute=AsyncMock(return_value=("document", "job")))
    public = PublicProcessing(
        SimpleNamespace(document_store=object()), None, submissions, None, None, None
    )
    invitation_id, question_id, document_id, key = uuid4(), uuid4(), uuid4(), uuid4()
    reference = EntryReference(run_id=uuid4(), stage_id=uuid4(), run_revision=1)
    result = await public.submit_file(
        "nota.txt",
        b"contenido ficticio",
        document_id,
        None,
        key,
        invitation_id=invitation_id,
        invitation_question_id=question_id,
        journal_reference=reference,
    )
    assert result == ("document", "job")
    original, used_key = submissions.execute.await_args.args
    assert (original.id, original.content, used_key) == (document_id, "contenido ficticio", key)
    assert submissions.execute.await_args.kwargs == {
        "invitation_id": invitation_id,
        "invitation_question_id": question_id,
        "journal_reference": reference,
    }


@pytest.mark.anyio
async def test_file_http_parses_association_and_translates_ownership_errors():
    calls = []

    class Actions:
        async def submit_file(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise InvitationError("invitation_question_not_found")

    async def get_actions():
        return Actions()

    async def get_limits():
        return SimpleNamespace(document_max_upload_bytes=1024)

    app = FastAPI()
    app.include_router(build_router(get_actions, get_limits))
    invitation_id, question_id, run_id, stage_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        result = await client.post(
            "/v2/documents/files",
            files={"file": ("nota.txt", b"texto ficticio", "text/plain")},
            data={
                "invitation_id": str(invitation_id),
                "invitation_question_id": str(question_id),
                "journal_reference": json.dumps(
                    {"run_id": str(run_id), "stage_id": str(stage_id), "run_revision": 1}
                ),
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert result.status_code == 404
        assert calls[0][1]["invitation_id"] == invitation_id
        assert calls[0][1]["invitation_question_id"] == question_id
        assert calls[0][1]["journal_reference"] == EntryReference(
            run_id=run_id, stage_id=stage_id, run_revision=1
        )
        invalid = await client.post(
            "/v2/documents/files",
            files={"file": ("nota.txt", b"texto")},
            data={"journal_reference": "not-json"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert invalid.status_code == 422
        assert len(calls) == 1
