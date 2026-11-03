"""Application behavior with memory ports, including commit/replay failures."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.journals.contracts import ActivateRun, AdjustRun, ChangeLifecycle, EditIntention
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.core.journals.ports import OwnerAccess
from src.core.journals.templates import PREPARATION_TEMPLATE
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals
from src.use_cases.journals.reconcile import InstallJournalTemplates, ReconcileJournals


@pytest.fixture
def anyio_backend():
    return "asyncio"


class MemoryJournals:
    def __init__(self):
        self.owner = uuid4()
        self.now = datetime(2026, 11, 3, 12, tzinfo=UTC)
        self.access = OwnerAccess(exists=True, enabled=True, workspace_active=True)
        self.definitions, self.runs, self.receipts = {}, {}, {}
        self.fail_commit = False
        self.fail_receipt = False

    @asynccontextmanager
    async def transaction(self, owner):
        runs, receipts = dict(self.runs), dict(self.receipts)

        async def access():
            return (
                self.access
                if owner == self.owner
                else OwnerAccess(
                    exists=False,
                    enabled=False,
                    workspace_active=False,
                )
            )

        async def lock_owner():
            pass

        async def now():
            return self.now

        async def receipt(key):
            return receipts.get((owner, key))

        async def template(identifier, version):
            return self.definitions.get((identifier, version))

        async def run(identifier, revision=None):
            matches = [
                r
                for (o, i, v), r in runs.items()
                if o == owner and i == identifier and (revision is None or v == revision)
            ]
            return max(matches, key=lambda r: r.revision) if matches else None

        async def current():
            identifiers = {i for o, i, _ in runs if o == owner}
            for identifier in identifiers:
                candidate = await run(identifier)
                if candidate.status == "active":
                    return candidate
            return None

        async def save(value, *, expected_revision):
            previous = await run(value.id)
            if (previous.revision if previous else None) != expected_revision:
                raise JournalError("journal_revision_conflict")
            runs[(owner, value.id, value.revision)] = value

        async def record_receipt(value):
            if self.fail_receipt:
                raise JournalStorageUnavailable()
            receipts[(owner, value.key)] = value

        yield SimpleNamespace(**locals())
        if self.fail_commit:
            raise JournalStorageUnavailable()
        self.runs, self.receipts = runs, receipts

    async def install_template(self, template):
        key = template.id, template.version
        if key in self.definitions and self.definitions[key] != template:
            raise JournalError("journal_template_version_conflict")
        self.definitions[key] = template

    async def due_owners(self, *, at, limit):
        async with self.transaction(self.owner) as transaction:
            run = await transaction.current()
        return (self.owner,) if run and run.stages[-1].ends_at <= (at or self.now) else ()


@pytest.fixture
async def env():
    repository = MemoryJournals()
    await InstallJournalTemplates(repository).execute((PREPARATION_TEMPLATE,))
    manage = ManageJournals(repository, enabled=True, clock=lambda: repository.now)
    query = QueryJournals(repository, enabled=True, clock=lambda: repository.now)
    command = ActivateRun(template_id=PREPARATION_TEMPLATE.id, template_version=1, timezone="UTC")
    return SimpleNamespace(
        repo=repository, manage=manage, query=query, command=command, owner=repository.owner
    )


@pytest.mark.anyio
async def test_response_lost_then_replayed_returns_the_original_receipt_even_when_disabled(env):
    key = uuid4()
    first = await env.manage.activate(env.owner, env.command, key)
    env.repo.now += timedelta(days=1)
    env.manage.enabled = False
    assert await env.manage.activate(env.owner, env.command, key) == first
    assert len(env.repo.runs) == len(env.repo.receipts) == 1
    with pytest.raises(JournalError, match="journals_disabled"):
        await env.manage.activate(env.owner, env.command, uuid4())


@pytest.mark.anyio
async def test_shared_key_cannot_be_reused_for_another_command_or_action(env):
    key = uuid4()
    receipt = await env.manage.activate(env.owner, env.command, key)
    with pytest.raises(JournalError, match="journal_idempotency_conflict"):
        await env.manage.activate(
            env.owner, env.command.model_copy(update={"timezone": "Etc/UTC"}), key
        )
    with pytest.raises(JournalError, match="journal_idempotency_conflict"):
        await env.manage.lifecycle(
            env.owner, receipt.run_id, ChangeLifecycle(expected_revision=1, action="pause"), key
        )


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["fail_commit", "fail_receipt"])
async def test_no_acknowledgement_or_partial_history_when_atomic_commit_fails(env, failure):
    key = uuid4()
    setattr(env.repo, failure, True)
    with pytest.raises(JournalStorageUnavailable):
        await env.manage.activate(env.owner, env.command, key)
    assert not env.repo.runs and not env.repo.receipts
    setattr(env.repo, failure, False)
    receipt = await env.manage.activate(env.owner, env.command, key)
    assert receipt.revision == 1 and len(env.repo.runs) == 1


@pytest.mark.anyio
async def test_full_lifecycle_preserves_historical_intention_and_configuration(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    env.repo.now += timedelta(days=1)
    before = await env.query.resolve(env.owner, env.repo.now)
    await env.manage.edit_intention(
        env.owner,
        receipt.run_id,
        EditIntention(expected_revision=1, text="PRIVATE_INTENTION"),
        uuid4(),
    )
    assert (await env.query.intention(env.owner, receipt.run_id)).text == "PRIVATE_INTENTION"
    assert await env.query.intention(env.owner, receipt.run_id, 1) is None
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=2, action="pause"), uuid4()
    )
    assert (await env.query.resolve(env.owner, env.repo.now)).mode == "free"
    env.repo.now += timedelta(days=2)
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=3, action="resume"), uuid4()
    )
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=4, action="advance"), uuid4()
    )
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=5, action="close"), uuid4()
    )
    assert (await env.query.public(env.owner, receipt.run_id)).status == "closed"
    assert await env.query.validate_reference(env.owner, before.reference) == before.reference
    assert (
        "PRIVATE_INTENTION"
        not in (
            await env.query.administrative(
                env.owner,
                receipt.run_id,
            )
        ).model_dump_json()
    )
    assert len(env.repo.runs) == 6


@pytest.mark.anyio
async def test_adjustment_conflict_does_not_overwrite_a_more_recent_revision(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    env.repo.now += timedelta(days=1)
    command = AdjustRun(
        expected_revision=1,
        remaining_stages=PREPARATION_TEMPLATE.stages,
        instructions="Una orientación específica",
    )
    await env.manage.adjust(env.owner, receipt.run_id, command, uuid4())
    with pytest.raises(JournalError, match="journal_revision_conflict"):
        await env.manage.adjust(env.owner, receipt.run_id, command, uuid4())
    assert (
        await env.query.administrative(env.owner, receipt.run_id)
    ).instructions == command.instructions
    assert len(env.repo.runs) == 2


@pytest.mark.anyio
async def test_expired_active_slot_is_completed_in_the_same_activation_transaction(env):
    first = await env.manage.activate(env.owner, env.command, uuid4())
    env.repo.now += timedelta(days=40)
    assert (await env.query.public(env.owner, first.run_id)).status == "completed"
    second = await env.manage.activate(env.owner, env.command, uuid4())
    assert first.run_id != second.run_id
    assert env.repo.runs[(env.owner, first.run_id, 2)].change == "completion"


@pytest.mark.anyio
async def test_reconciliation_catches_up_once_without_a_daily_counter(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    env.repo.now += timedelta(days=8)
    assert (await env.query.resolve(env.owner, env.repo.now)).stage_objective == (
        PREPARATION_TEMPLATE.stages[1].objective
    )
    service = ReconcileJournals(env.repo, clock=lambda: env.repo.now)
    assert await service.execute() == 0
    env.repo.now += timedelta(days=30)
    assert await service.execute() == 1
    assert await service.execute() == 0
    assert (await env.query.public(env.owner, receipt.run_id)).status == "completed"


@pytest.mark.anyio
async def test_authorization_is_enforced_before_mutation_and_historical_reads(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    with pytest.raises(JournalError, match="journal_owner_not_found"):
        await env.query.public(uuid4(), receipt.run_id)
    env.repo.access = OwnerAccess(exists=True, enabled=True, workspace_active=False)
    with pytest.raises(JournalError, match="journal_workspace_unavailable"):
        await env.manage.lifecycle(
            env.owner, receipt.run_id, ChangeLifecycle(expected_revision=1, action="pause"), uuid4()
        )
    assert len(env.repo.runs) == 1


@pytest.mark.anyio
async def test_disabled_flag_keeps_reads_and_historical_references(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    context = await env.query.resolve(env.owner, env.repo.now)
    env.query.enabled = False
    with pytest.raises(JournalError, match="journals_disabled"):
        await env.query.resolve(env.owner, env.repo.now)
    assert (await env.query.public(env.owner, receipt.run_id)).id == receipt.run_id
    assert await env.query.validate_reference(env.owner, context.reference) == context.reference


@pytest.mark.anyio
async def test_template_installation_is_idempotent_but_cannot_rewrite_a_version(env):
    installer = InstallJournalTemplates(env.repo)
    await installer.execute((PREPARATION_TEMPLATE,))
    with pytest.raises(JournalError, match="journal_template_version_conflict"):
        await installer.execute(
            (PREPARATION_TEMPLATE.model_copy(update={"name": "Otro template"}),)
        )
    assert len(env.repo.definitions) == 1


@pytest.mark.anyio
async def test_dispatcher_composition_does_not_touch_storage_when_disabled(monkeypatch):
    from src.bootstrap import journals

    monkeypatch.setattr(journals, "get_settings", lambda: SimpleNamespace(journals_enabled=False))

    def unexpected_repository():
        raise AssertionError("Disabled reconciliation must not access storage")

    monkeypatch.setattr(journals, "build_journals", unexpected_repository)
    assert await journals.reconcile_journals() == 0


@pytest.mark.anyio
async def test_dispatcher_composition_installs_and_reconciles_when_enabled(env, monkeypatch):
    from src.bootstrap import journals

    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    env.repo.now += timedelta(days=40)
    monkeypatch.setattr(journals, "get_settings", lambda: SimpleNamespace(journals_enabled=True))
    monkeypatch.setattr(journals, "build_journals", lambda: env.repo)
    assert await journals.reconcile_journals() == 1
    assert await journals.reconcile_journals() == 0
    assert (await env.query.public(env.owner, receipt.run_id)).status == "completed"


def test_shared_and_admin_settings_default_to_disabled_without_reading_dotenv(monkeypatch):
    from src.bootstrap.administration_settings import AdministrationSettings
    from src.bootstrap.settings import Settings

    monkeypatch.delenv("JOURNALS_ENABLED", raising=False)
    assert Settings(_env_file=None).journals_enabled is False
    assert AdministrationSettings(_env_file=None).journals_enabled is False


def test_application_loads_without_infrastructure():
    import subprocess
    import sys

    source = """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'sqlalchemy', 'taskiq', 'openai'} or any(
            fullname == name or fullname.startswith(name + '.')
            for name in ('src.adapters', 'src.bootstrap')
        ):
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from src.use_cases.journals import manage, query, reconcile
"""
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True, text=True)
