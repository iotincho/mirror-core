"""Identity/recovery/workspace policies with memory ports and synthetic credentials."""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.auth.identity import AccountCredentials
from src.core.auth.recovery import (
    MailResult,
    RecoveryAddress,
    RecoveryDelivery,
    RecoveryError,
    RecoveryIP,
)
from src.core.workspaces.models import (
    Workspace,
    WorkspaceProvisioningError,
    WorkspaceStatus,
    WorkspaceUnavailable,
)
from src.use_cases.auth.authenticate import AuthenticateUser
from src.use_cases.auth.recover_password import RecoverPassword
from src.use_cases.auth.send_recovery_email import SendRecoveryEmail
from src.use_cases.workspaces.access import WorkspaceAccess
from src.use_cases.workspaces.provision import WorkspaceProvisioner


@pytest.fixture
def anyio_backend():
    return "asyncio"


class SyntheticSecrets:
    def mac(self, purpose, value):
        return f"synthetic:{purpose}:{value}"

    def email_key(self, email):
        return self.mac("email", email.strip().lower())

    def password_mac(self, user):
        return self.mac("version", f"{user.id}:{user.session_version}")

    def encrypt_code(self, code):
        return "synthetic-protected:" + code

    def decrypt_code(self, ciphertext):
        return ciphertext.removeprefix("synthetic-protected:")

    encrypt = encrypt_code
    decrypt = decrypt_code


class MemoryRecovery:
    def __init__(self, account):
        self.account = account
        self.clock = datetime.now(UTC)
        self.addresses, self.ips, self.deliveries = {}, {}, {}
        self.revoked = []

    @asynccontextmanager
    async def transaction(self):
        pending = deepcopy(self)
        yield pending
        self.__dict__.update(pending.__dict__)

    async def now(self):
        return self.clock

    async def ip(self, key):
        return self.ips.setdefault(key, RecoveryIP(key))

    async def address(self, key):
        return self.addresses.setdefault(key, RecoveryAddress(key))

    async def user(self, email, *, lock=False):
        return self.account if self.account.email.lower() == email.strip().lower() else None

    async def user_by_id(self, owner):
        return self.account if self.account.id == owner else None

    async def enqueue_email(self, delivery_id, processing_id, user_id, key, challenge, now):
        self.deliveries[delivery_id] = RecoveryDelivery(
            delivery_id,
            user_id,
            key,
            challenge,
            processing_id,
        )

    async def delivery_context(self, identifier):
        delivery = self.deliveries.get(identifier)
        return delivery, self.addresses.get(delivery.address_key) if delivery else None

    async def revoke_access(self, owner, now):
        self.revoked.append(owner)


def recovery():
    account = AccountCredentials(uuid4(), "owner@example.test", "synthetic-old", 2, True, True)
    store = MemoryRecovery(account)
    passwords = SimpleNamespace(hash=lambda value: "synthetic-hash:" + value)
    return store, RecoverPassword(store, SyntheticSecrets(), passwords)


@pytest.mark.anyio
async def test_rejected_code_commits_attempt_and_reset_consumes_once_and_revokes_owner():
    store, case = recovery()
    await case.request(store.account.email, "192.0.2.1")
    address = next(iter(store.addresses.values()))
    code = SyntheticSecrets().decrypt_code(address.code_ciphertext)
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(RecoveryError, match="recovery_invalid_code"):
        await case.reset(store.account.email, wrong, "valid-new-password", "192.0.2.2")
    assert next(iter(store.addresses.values())).failed_attempts == 1
    assert not store.revoked
    await case.reset(store.account.email, code, "valid-new-password", "192.0.2.2")
    assert store.account.session_version == 3
    assert store.account.hashed_password == "synthetic-hash:valid-new-password"
    assert store.revoked == [store.account.id]
    address = next(iter(store.addresses.values()))
    assert address.code_mac is None and address.code_ciphertext is None
    with pytest.raises(RecoveryError, match="recovery_invalid_code"):
        await case.reset(store.account.email, code, "another-new-password", "192.0.2.2")
    assert store.account.session_version == 3


@pytest.mark.anyio
async def test_recovery_delivery_retries_with_stable_identity_and_replay_does_not_send():
    store, case = recovery()
    await case.request(store.account.email, "192.0.2.1")
    delivery = next(iter(store.deliveries.values()))
    transport = SimpleNamespace(
        send=AsyncMock(
            side_effect=[
                MailResult(retryable=True, retry_after=25),
                MailResult(accepted=True, provider_id="fake"),
            ]
        )
    )
    mail = SendRecoveryEmail(store, SyntheticSecrets(), transport)
    context = SimpleNamespace(
        record=SimpleNamespace(
            id=delivery.processing_id,
            user_id=delivery.user_id,
            resource_id=delivery.id,
            stage_attempts=1,
        ),
        assert_lease=AsyncMock(),
    )
    from src.core.processing.errors import WorkflowFailure

    with pytest.raises(WorkflowFailure) as retry:
        await mail.execute(context)
    assert retry.value.retry_delay == 25
    assert store.deliveries[delivery.id].status == "retrying"
    store.clock += timedelta(seconds=25)
    await mail.execute(context)
    await mail.execute(context)
    assert transport.send.await_count == 2
    assert transport.send.await_args_list[0].args == transport.send.await_args_list[1].args
    assert store.deliveries[delivery.id].status == "accepted"


@pytest.mark.anyio
async def test_authentication_confirms_local_login_without_changing_session_version():
    account = AccountCredentials(uuid4(), "owner@example.test", "old-hash", 7, True, False)
    accounts = SimpleNamespace(
        credentials=AsyncMock(return_value=deepcopy(account)), confirm_login=AsyncMock()
    )
    passwords = SimpleNamespace(verify_and_update=lambda *_: (True, "upgraded-hash"))
    result = await AuthenticateUser(accounts, passwords).execute(account.email, "synthetic")
    accounts.confirm_login.assert_awaited_once_with(
        result,
        {
            "hashed_password": "upgraded-hash",
            "password_login_enabled": True,
        },
    )
    assert result.session_version == 7


class MemoryWorkspaces:
    def __init__(self):
        self.rows = {}

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def get_or_create(self, owner, **allocation):
        return self.rows.setdefault(
            owner,
            Workspace(
                owner,
                allocation["arcadedb_instance_key"],
                f"db_{owner.hex}",
                f"user_{owner.hex}",
                allocation["graph_secret_ciphertext"],
            ),
        )

    async def get(self, owner, *, for_update=False):
        return self.rows.get(owner)

    read = get


@pytest.mark.anyio
async def test_provisioning_retry_keeps_allocation_and_suspension_blocks_force():
    store, secrets = MemoryWorkspaces(), SyntheticSecrets()
    remote = SimpleNamespace(provision=AsyncMock(side_effect=[WorkspaceProvisioningError(), None]))
    provisioner = WorkspaceProvisioner(
        store,
        remote,
        secrets,
        instance_key="primary",
        schema_version="synthetic/v1",
    )
    owner = uuid4()
    assert (await provisioner.provision(owner)).status == WorkspaceStatus.FAILED
    assert (await provisioner.provision(owner)).status == WorkspaceStatus.ACTIVE
    assert remote.provision.await_args_list[0] == remote.provision.await_args_list[1]
    store.rows[owner].status = WorkspaceStatus.SUSPENDED
    assert (await provisioner.provision(owner, force=True)).status == WorkspaceStatus.SUSPENDED
    assert remote.provision.await_count == 2


@pytest.mark.anyio
async def test_resolution_denies_other_instance_and_never_falls_back_to_another_owner():
    store, secrets = MemoryWorkspaces(), SyntheticSecrets()
    owner, other = uuid4(), uuid4()
    store.rows[owner] = Workspace(
        owner, "primary", "db", "user", "protected", status=WorkspaceStatus.ACTIVE
    )
    access = WorkspaceAccess(store, secrets, "primary")
    assert (await access.resolve(owner)).workspace.user_id == owner
    with pytest.raises(WorkspaceUnavailable):
        await access.resolve(other)
    store.rows[owner].arcadedb_instance_key = "another-instance"
    assert await access.status(owner) == "unavailable"
    with pytest.raises(WorkspaceUnavailable):
        await access.resolve(owner)
