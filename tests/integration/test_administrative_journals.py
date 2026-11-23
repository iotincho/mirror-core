"""LAN configuration API with real disposable SQL, no originals or providers."""

# ruff: noqa: F811

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from test_administration import anyio_backend, env  # noqa: F401

from src.adapters.access.api.administration import journal_schemas
from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.journal_models import JournalReceiptRecord, JournalRunRecord
from src.adapters.storage.postgres.journals import PostgresJournals
from src.bootstrap.administration import app, get_read_journals, get_write_journals
from src.core.journals.contracts import EditIntention
from src.core.journals.errors import JournalStorageUnavailable
from src.core.journals.preparation_catalog import PREPARATION_TEMPLATE_V2
from src.use_cases.journals.administration import AdministerJournals

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("ADMIN_TEST_DATABASE_URL"), reason="requires isolated admin_test PostgreSQL"
    ),
]


@pytest.fixture
async def journals(env):
    sessions, owners, _, client = env
    repository = PostgresJournals(sessions)
    await repository.install_template(PREPARATION_TEMPLATE_V2)
    settings = SimpleNamespace(enabled=True)
    service = AdministerJournals(repository, enabled=True)
    app.dependency_overrides[get_read_journals] = lambda: AdministerJournals(
        PostgresJournals(sessions, read_only=True), enabled=settings.enabled
    )
    app.dependency_overrides[get_write_journals] = lambda: (
        service if settings.enabled else AdministerJournals(repository, enabled=False)
    )
    return SimpleNamespace(
        sessions=sessions,
        owner=owners[0],
        other=owners[2],
        inactive=owners[1],
        client=client,
        service=service,
        settings=settings,
        path=f"/api/admin/users/{owners[0]}/journals",
        activation=dict(
            template_id=str(PREPARATION_TEMPLATE_V2.id),
            template_version=2,
            timezone="America/Argentina/Buenos_Aires",
        ),
    )


def headers(key=None):
    return {"Idempotency-Key": str(key or uuid4()), "Origin": "http://admin.test"}


async def activate(journals):
    response = await journals.client.post(
        journals.path, json=journals.activation, headers=headers()
    )
    assert response.status_code == 200, response.text
    return response.json()


async def detail(journals, receipt):
    response = await journals.client.get(f"{journals.path}/{receipt['run_id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_preview_is_read_only_and_activation_exposes_only_configuration(journals):
    j = journals
    templates = await j.client.get("/api/admin/journals/templates")
    assert templates.status_code == 200
    assert any(t["version"] == 2 for t in templates.json()["items"])
    read = app.dependency_overrides[get_read_journals]()
    async with read.repository.transaction(j.owner) as tx:
        assert await tx.session.scalar(text("SHOW transaction_read_only")) == "on"
        assert await tx.session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
    preview = await j.client.post(
        j.path + "/preview-activation", json=j.activation, headers=headers()
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["stages"]) == 4
    assert (await j.client.get(j.path)).json()["total"] == 0
    receipt = await activate(j)
    assert set(receipt) == {"key", "run_id", "revision", "operation", "recorded_at"}
    await j.service.actions.edit_intention(
        j.owner,
        UUID(receipt["run_id"]),
        EditIntention(expected_revision=1, text="PRIVATE_PERSONAL_INTENTION"),
        uuid4(),
    )
    response = await j.client.get(j.path)
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["items"][0]["run"]["revision"] == 2
    assert "PRIVATE_PERSONAL_INTENTION" not in response.text
    assert "capture_reference" not in response.text
    assert "owner_id" not in response.text
    history = await j.client.get(f"{j.path}/{receipt['run_id']}/revisions?limit=1")
    assert history.json()["total"] == 2 and history.json()["items"][0]["change"] == "intention"
    assert "PRIVATE_PERSONAL_INTENTION" not in history.text


async def test_response_lost_after_commit_replays_the_same_activation(journals, monkeypatch):
    j, key = journals, uuid4()
    original = journal_schemas.receipt_response

    def broken_response(value):
        raise SQLAlchemyError("PRIVATE_RESPONSE_DETAILS")

    monkeypatch.setattr(journal_schemas, "receipt_response", broken_response)
    lost = await j.client.post(j.path, json=j.activation, headers=headers(key))
    assert lost.status_code == 503 and "PRIVATE" not in lost.text
    monkeypatch.setattr(journal_schemas, "receipt_response", original)
    first = await j.client.post(j.path, json=j.activation, headers=headers(key))
    second = await j.client.post(j.path, json=j.activation, headers=headers(key))
    assert first.status_code == 200 and first.json() == second.json()
    async with j.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalRunRecord)
                .where(JournalRunRecord.owner_id == j.owner)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalReceiptRecord)
                .where(JournalReceiptRecord.owner_id == j.owner)
            )
            == 1
        )


async def test_failed_commit_is_never_reported_as_saved(journals):
    j = journals

    class FailingRepository(PostgresJournals):
        @asynccontextmanager
        async def transaction(self, owner):
            async with super().transaction(owner) as tx:
                yield tx
                raise JournalStorageUnavailable()

    app.dependency_overrides[get_write_journals] = lambda: AdministerJournals(
        FailingRepository(j.sessions), enabled=True
    )
    result = await j.client.post(j.path, json=j.activation, headers=headers())
    assert result.status_code == 503 and result.json()["detail"] == "journal_storage_unavailable"
    assert (await j.client.get(j.path)).json()["total"] == 0


async def test_partial_catalog_review_keeps_other_stages_and_replay_after_intention_edit(journals):
    j = journals
    receipt = await activate(j)
    original = await detail(j, receipt)
    key = uuid4()
    body = dict(
        expected_revision=1,
        remaining_stages=[s["definition"] for s in original["stages"]],
        purpose="Explorar una dirección personal con curiosidad.",
        reviewed_catalogs=[
            {
                "stage_key": original["catalogs"][0]["stage_key"],
                "prompts": original["catalogs"][0]["prompts"],
            }
        ],
    )
    preview = await j.client.post(
        f"{j.path}/{receipt['run_id']}/preview", json=body, headers=headers()
    )
    assert preview.status_code == 200, preview.text
    proposed = preview.json()
    assert len(proposed["catalog_review_required"]) == 3 and len(proposed["catalogs"]) == 4
    assert (await detail(j, receipt))["run"]["revision"] == 1
    first = await j.client.patch(f"{j.path}/{receipt['run_id']}", json=body, headers=headers(key))
    assert first.status_code == 200, first.text
    await j.service.actions.edit_intention(
        j.owner,
        UUID(receipt["run_id"]),
        EditIntention(expected_revision=2, text="PRIVATE_NEW_INTENTION"),
        uuid4(),
    )
    replay = await j.client.patch(f"{j.path}/{receipt['run_id']}", json=body, headers=headers(key))
    assert replay.json() == first.json()
    assert (await detail(j, receipt))["run"]["revision"] == 3
    stale = await j.client.patch(f"{j.path}/{receipt['run_id']}", json=body, headers=headers())
    assert stale.status_code == 409 and stale.json()["detail"] == "journal_revision_conflict"


async def test_foreign_origins_invalid_bodies_and_account_scope_are_rejected(journals):
    j = journals
    for origin in ["http://public.test", "http://admin.test:9999", "https://admin.test", "null"]:
        response = await j.client.post(
            j.path, json=j.activation, headers={**headers(), "Origin": origin}
        )
        assert response.status_code == 403
    bad = await j.client.post(
        j.path,
        json={**j.activation, "owner_id": str(j.other), "private": "PRIVATE_INPUT"},
        headers=headers(),
    )
    assert bad.status_code == 422 and "PRIVATE_INPUT" not in bad.text
    assert (await j.client.post(j.path, json=j.activation)).status_code == 422
    receipt = await activate(j)
    for identifier in [str(j.other), str(uuid4())]:
        response = await j.client.get(f"/api/admin/users/{identifier}/journals/{receipt['run_id']}")
        assert response.status_code == 404
    missing = await j.client.get(f"/api/admin/users/{uuid4()}/journals")
    assert missing.status_code == 404


async def test_disabled_function_and_account_keep_configuration_readable(journals):
    j = journals
    receipt = await activate(j)
    j.settings.enabled = False
    response = await j.client.get(j.path)
    assert response.json()["enabled"] is False and response.json()["total"] == 1
    blocked = await j.client.post(
        f"{j.path}/{receipt['run_id']}/actions",
        json={"expected_revision": 1, "action": "pause"},
        headers=headers(),
    )
    assert blocked.status_code == 409 and blocked.json()["detail"] == "journals_disabled"
    j.settings.enabled = True
    async with j.sessions.begin() as session:
        await session.execute(update(User).where(User.id == j.owner).values(is_active=False))
    response = await j.client.get(j.path)
    assert response.json()["account_active"] is False and response.json()["total"] == 1
    assert (await j.client.get(f"{j.path}/{receipt['run_id']}?revision=1")).status_code == 200
    blocked = await j.client.post(
        f"{j.path}/{receipt['run_id']}/actions",
        json={"expected_revision": 1, "action": "close"},
        headers=headers(),
    )
    assert blocked.status_code == 409


async def test_lifecycle_repetition_and_bounded_history(journals):
    j = journals
    identifiers = []
    for _ in range(3):
        receipt = await activate(j)
        identifiers.append(receipt["run_id"])
        for revision, action in enumerate(["pause", "resume", "close"], 1):
            result = await j.client.post(
                f"{j.path}/{receipt['run_id']}/actions",
                json={"expected_revision": revision, "action": action},
                headers=headers(),
            )
            assert result.status_code == 200, result.text
        history = await j.client.get(f"{j.path}/{receipt['run_id']}/revisions?limit=1&offset=1")
        assert history.json()["total"] == 4 and history.json()["items"][0]["revision"] == 3
    await activate(j)
    first = (await j.client.get(j.path + "?limit=1")).json()
    second = (await j.client.get(j.path + "?limit=1&offset=1")).json()
    assert first["total"] == second["total"] == 4
    assert first["items"][0]["run"]["status"] == "active"
    assert first["items"][0]["run"]["id"] != second["items"][0]["run"]["id"]
    assert len(set(identifiers)) == 3


async def test_two_http_activations_with_the_same_key_confirm_one_run(journals):
    j, key = journals, uuid4()
    first, second = await asyncio.gather(
        *[j.client.post(j.path, json=j.activation, headers=headers(key)) for _ in range(2)]
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert (await j.client.get(j.path)).json()["total"] == 1


async def test_future_stage_can_be_added_then_approved_without_replacing_other_catalogs(journals):
    j = journals
    receipt = await activate(j)
    original = await detail(j, receipt)
    new_stage = dict(
        key="extra-exploration",
        name="Volver sobre lo explorado",
        objective="Dar lugar a preguntas que siguen abiertas.",
        instructions="",
        duration_days=3,
    )
    body = dict(
        expected_revision=1,
        remaining_stages=[s["definition"] for s in original["stages"]] + [new_stage],
        reviewed_catalogs=[],
    )
    path = f"{j.path}/{receipt['run_id']}"
    result = await j.client.patch(path, json=body, headers=headers())
    assert result.status_code == 200, result.text
    saved = await detail(j, receipt)
    assert len(saved["stages"]) == 5
    assert saved["catalog_review_required"] == ["extra-exploration"]
    body["expected_revision"] = 2
    body["reviewed_catalogs"] = [
        dict(
            stage_key="extra-exploration",
            prompts=[
                dict(
                    key="extra-open-question",
                    gentle="¿Qué pregunta tenés presente?",
                    middle="¿Qué te gustaría dejar abierto?",
                    deep="¿Qué lugar querés darle a esa pregunta?",
                )
            ],
        )
    ]
    result = await j.client.patch(path, json=body, headers=headers())
    assert result.status_code == 200, result.text
    saved = await detail(j, receipt)
    assert len(saved["catalogs"]) == 5 and not saved["catalog_review_required"]
