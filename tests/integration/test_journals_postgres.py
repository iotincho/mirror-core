"""Real transactions and concurrent journal mutations in an isolated opt-in database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import InvitationPreference
from src.adapters.storage.postgres.journal_models import (
    JournalReceiptRecord,
    JournalRevisionRecord,
    JournalRunRecord,
    JournalStageRecord,
)
from src.adapters.storage.postgres.journals import JournalTransaction, PostgresJournals
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.journals.contracts import ActivateRun, AdjustRun, ChangeLifecycle, EditIntention
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.core.journals.templates import PREPARATION_TEMPLATE
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals
from src.use_cases.journals.reconcile import InstallJournalTemplates, ReconcileJournals

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("JOURNALS_TEST_DATABASE_URL"),
        reason="requires isolated journals PostgreSQL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def env():
    url = make_url(os.environ["JOURNALS_TEST_DATABASE_URL"])
    assert url.database.startswith("journals_test")
    engine = create_async_engine(url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owners = (uuid4(), uuid4())
    async with sessions.begin() as session:
        session.add_all(
            User(id=owner, email=f"{owner}@example.com", hashed_password="unused")
            for owner in owners
        )
        await session.flush()
        session.add_all(
            UserWorkspace(
                user_id=owner,
                arcadedb_instance_key="journals-test",
                database_name=f"test_{owner.hex}",
                graph_username=f"test_{owner.hex}",
                graph_secret_ciphertext="unused",
                status="active",
            )
            for owner in owners
        )
    repository = PostgresJournals(sessions)
    await InstallJournalTemplates(repository).execute((PREPARATION_TEMPLATE,))
    state = SimpleNamespace(now=datetime(2026, 11, 3, 12, tzinfo=UTC))
    command = ActivateRun(template_id=PREPARATION_TEMPLATE.id, template_version=1, timezone="UTC")
    manage = ManageJournals(repository, enabled=True, clock=lambda: state.now)
    query = QueryJournals(repository, enabled=True, clock=lambda: state.now)
    try:
        yield SimpleNamespace(
            repo=repository,
            sessions=sessions,
            owners=owners,
            owner=owners[0],
            manage=manage,
            query=query,
            command=command,
            state=state,
        )
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(User).where(User.id.in_(owners)))
        await engine.dispose()


async def counts(env):
    async with env.sessions() as session:
        return tuple(
            [
                await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.owner_id == env.owner,
                    )
                )
                for model in (JournalRunRecord, JournalRevisionRecord, JournalReceiptRecord)
            ]
        )


async def test_concurrent_distinct_activations_leave_one_active_run_and_one_receipt(env):
    results = await asyncio.gather(
        *[env.manage.activate(env.owner, env.command, uuid4()) for _ in range(6)],
        return_exceptions=True,
    )
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert all(
        isinstance(r, JournalError) and r.code == "journal_active_conflict"
        for r in results
        if isinstance(r, Exception)
    )
    assert await counts(env) == (1, 1, 1)


async def test_concurrent_replays_return_identical_receipts_without_extra_snapshots(env):
    key = uuid4()
    results = await asyncio.gather(
        *[env.manage.activate(env.owner, env.command, key) for _ in range(6)]
    )
    assert all(receipt == results[0] for receipt in results)
    assert await counts(env) == (1, 1, 1)
    with pytest.raises(JournalError, match="journal_idempotency_conflict"):
        await env.manage.activate(
            env.owner, env.command.model_copy(update={"timezone": "Etc/UTC"}), key
        )


async def test_sql_partial_unique_index_prevents_an_active_run_even_without_application_checks(env):
    await env.manage.activate(env.owner, env.command, uuid4())
    async with env.sessions() as session:
        first = await session.scalar(
            select(JournalRunRecord).where(JournalRunRecord.owner_id == env.owner)
        )
        values = {
            column.name: getattr(first, column.name)
            for column in JournalRunRecord.__table__.columns
        }
    with pytest.raises(IntegrityError) as error:
        async with env.sessions.begin() as session:
            await session.execute(insert(JournalRunRecord).values(**{**values, "id": uuid4()}))
    assert error.value.orig.__cause__.constraint_name == "uq_journal_active_owner"


async def test_concurrent_edits_require_a_fresh_revision_and_archive_the_winning_snapshot(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    env.state.now += timedelta(days=1)
    results = await asyncio.gather(
        *[
            env.manage.adjust(
                env.owner,
                receipt.run_id,
                AdjustRun(
                    expected_revision=1,
                    remaining_stages=PREPARATION_TEMPLATE.stages,
                    instructions=f"Orientación {index}",
                ),
                uuid4(),
            )
            for index in range(4)
        ],
        return_exceptions=True,
    )
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert all(
        isinstance(r, JournalError) and r.code == "journal_revision_conflict"
        for r in results
        if isinstance(r, Exception)
    )
    assert await counts(env) == (1, 2, 2)
    old = await env.query.administrative(env.owner, receipt.run_id, 1)
    assert old.instructions == PREPARATION_TEMPLATE.instructions
    assert (
        await env.query.administrative(env.owner, receipt.run_id)
    ).instructions != old.instructions


async def test_atomic_rollback_after_snapshots_and_stage_indices_before_receipt(env, monkeypatch):
    key = uuid4()
    original = JournalTransaction.record_receipt

    async def fail(self, receipt):
        raise JournalStorageUnavailable()

    monkeypatch.setattr(JournalTransaction, "record_receipt", fail)
    with pytest.raises(JournalStorageUnavailable):
        await env.manage.activate(env.owner, env.command, key)
    assert await counts(env) == (0, 0, 0)
    async with env.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalStageRecord)
                .where(
                    JournalStageRecord.owner_id == env.owner,
                )
            )
            == 0
        )
    monkeypatch.setattr(JournalTransaction, "record_receipt", original)
    assert (await env.manage.activate(env.owner, env.command, key)).revision == 1


async def test_commit_failure_never_acknowledges_a_successful_revision(env, monkeypatch):
    key = uuid4()
    original = JournalTransaction.record_receipt

    async def poison_deferred_constraint(self, receipt):
        await original(self, receipt)
        await self.session.execute(
            update(JournalRunRecord)
            .where(
                JournalRunRecord.id == receipt.run_id,
            )
            .values(revision=999)
        )

    monkeypatch.setattr(JournalTransaction, "record_receipt", poison_deferred_constraint)
    with pytest.raises(JournalStorageUnavailable):
        await env.manage.activate(env.owner, env.command, key)
    assert await counts(env) == (0, 0, 0)
    monkeypatch.setattr(JournalTransaction, "record_receipt", original)
    assert (await env.manage.activate(env.owner, env.command, key)).revision == 1


async def test_composite_membership_rejects_stage_or_receipt_from_another_owner(env):
    first = await env.manage.activate(env.owner, env.command, uuid4())
    async with env.sessions() as session:
        stage = await session.scalar(
            select(JournalStageRecord).where(JournalStageRecord.run_id == first.run_id)
        )
        values = {c.name: getattr(stage, c.name) for c in JournalStageRecord.__table__.columns}
    with pytest.raises(IntegrityError):
        async with env.sessions.begin() as session:
            await session.execute(
                insert(JournalStageRecord).values(
                    **{
                        **values,
                        "stage_id": uuid4(),
                        "position": 9,
                        "owner_id": env.owners[1],
                    }
                )
            )
    with pytest.raises(JournalError, match="journal_not_found"):
        await env.query.public(env.owners[1], first.run_id)
    context = await env.query.resolve(env.owner, env.state.now)
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        await env.query.validate_reference(env.owners[1], context.reference)


async def test_auto_completion_releases_slot_atomically_and_dispatchers_reconcile_once(env):
    first = await env.manage.activate(env.owner, env.command, uuid4())
    env.state.now += timedelta(days=35)
    assert (await env.query.public(env.owner, first.run_id)).status == "completed"
    service = ReconcileJournals(env.repo, clock=lambda: env.state.now)
    results = await asyncio.gather(*[service.execute() for _ in range(4)])
    assert sum(results) == 1 and await counts(env) == (1, 2, 1)
    assert (await env.manage.activate(env.owner, env.command, uuid4())).run_id != first.run_id


async def test_activation_reconciles_expired_current_without_waiting_for_dispatcher(env):
    first = await env.manage.activate(env.owner, env.command, uuid4())
    env.state.now += timedelta(days=35)
    second = await env.manage.activate(env.owner, env.command, uuid4())
    assert await counts(env) == (2, 3, 2)
    assert (await env.query.public(env.owner, first.run_id)).status == "completed"
    assert second.run_id != first.run_id


async def test_preferences_unchanged_and_publication_lock_serializes_journal_mutations(env):
    async with env.sessions.begin() as session:
        session.add(
            InvitationPreference(
                user_id=env.owner, enabled=False, local_time="17:00", timezone="UTC"
            )
        )
    async with env.sessions() as session:
        original = await session.get(InvitationPreference, env.owner)
        updated_at = original.updated_at
    waiting = None
    try:
        async with env.sessions.begin() as session:
            await session.execute(
                select(InvitationPreference)
                .where(
                    InvitationPreference.user_id == env.owner,
                )
                .with_for_update()
            )
            waiting = asyncio.create_task(env.manage.activate(env.owner, env.command, uuid4()))
            await asyncio.sleep(0.05)
            assert not waiting.done()
        await asyncio.wait_for(waiting, timeout=5)
    finally:
        if waiting and not waiting.done():
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
    async with env.sessions() as session:
        preference = await session.get(InvitationPreference, env.owner)
        assert (preference.enabled, preference.local_time, preference.timezone) == (
            False,
            "17:00",
            "UTC",
        )
        assert preference.updated_at == updated_at


async def test_intention_archived_and_reference_accepted_after_pause_resume_and_close(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    before = await env.query.resolve(env.owner, env.state.now)
    env.state.now += timedelta(days=1)
    await env.manage.edit_intention(
        env.owner,
        receipt.run_id,
        EditIntention(expected_revision=1, text="PRIVATE_SYNTHETIC"),
        uuid4(),
    )
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=2, action="pause"), uuid4()
    )
    env.state.now += timedelta(days=2)
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=3, action="resume"), uuid4()
    )
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=4, action="close"), uuid4()
    )
    assert await env.query.validate_reference(env.owner, before.reference) == before.reference
    assert await env.query.intention(env.owner, receipt.run_id, 1) is None
    assert (await env.query.intention(env.owner, receipt.run_id, 2)).text == "PRIVATE_SYNTHETIC"
    assert (
        "PRIVATE_SYNTHETIC"
        not in (
            await env.query.administrative(
                env.owner,
                receipt.run_id,
            )
        ).model_dump_json()
    )


async def test_template_version_cannot_be_rewritten_and_queries_are_bounded(env):
    await env.repo.install_template(PREPARATION_TEMPLATE)
    changed = PREPARATION_TEMPLATE.model_copy(update={"purpose": "Un propósito distinto"})
    with pytest.raises(JournalError, match="journal_template_version_conflict"):
        await env.repo.install_template(changed)
    assert PREPARATION_TEMPLATE in await env.repo.templates()
    with pytest.raises(ValueError, match="journal_invalid_page_limit"):
        await env.repo.templates(0)


async def test_suspended_workspace_and_missing_account_cannot_activate(env):
    async with env.sessions.begin() as session:
        await session.execute(
            update(UserWorkspace)
            .where(
                UserWorkspace.user_id == env.owner,
            )
            .values(status="suspended")
        )
    with pytest.raises(JournalError, match="journal_workspace_unavailable"):
        await env.manage.activate(env.owner, env.command, uuid4())
    with pytest.raises(JournalError, match="journal_owner_not_found"):
        await env.manage.activate(uuid4(), env.command, uuid4())
    assert await counts(env) == (0, 0, 0)


async def test_corrupt_snapshot_identity_is_unavailable_without_exposing_content(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    async with env.sessions.begin() as session:
        row = await session.get(JournalRevisionRecord, (receipt.run_id, 1))
        row.snapshot = {**row.snapshot, "owner_id": str(env.owners[1])}
    with pytest.raises(JournalStorageUnavailable) as error:
        await env.query.public(env.owner, receipt.run_id)
    assert str(error.value) == "journal_storage_unavailable"


async def test_invalid_configuration_is_not_reported_as_a_storage_outage(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    with pytest.raises(ValidationError):
        await env.manage.edit_intention(
            env.owner,
            receipt.run_id,
            EditIntention(expected_revision=1, text=" "),
            uuid4(),
        )
    assert await counts(env) == (1, 1, 1)
