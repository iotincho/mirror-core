"""Invitation/inbox/admin policies run with memory ports and no framework or storage."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.administration.facts import ActivityFacts, SummaryFacts
from src.core.administration.inventory import ReceiptMetadata
from src.core.exteriorization.models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    PushResult,
    PushSubscription,
)
from src.use_cases.administration.query import Administration, AdministrationError
from src.use_cases.administration.sync_inventory import SyncInventory
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations
from src.use_cases.exteriorization.send_invitation import SendInvitation
from src.use_cases.notifications.center import NotificationCenter


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def transaction(state):
    yield state


def repository(state):
    return SimpleNamespace(transaction=lambda: transaction(state))


@pytest.mark.anyio
async def test_daily_generation_keeps_inbox_without_push_or_new_occurrences_on_replay():
    now = datetime(2026, 10, 23, 21, tzinfo=UTC)
    preference = InvitationPreference(
        uuid4(), True, "20:30", "UTC", now.replace(hour=20, minute=30)
    )
    persisted = []

    async def add(invitation):
        persisted.append(("invitation", invitation))

    async def notify(invitation):
        persisted.append(("inbox", invitation))

    state = SimpleNamespace(
        now=AsyncMock(return_value=now),
        reconcile_deliveries=AsyncMock(),
        due_preferences=AsyncMock(side_effect=[[preference], []]),
        workspace_active=AsyncMock(return_value=True),
        active_subscriptions=AsyncMock(return_value=[]),
        scheduled_exists=AsyncMock(return_value=False),
        history=AsyncMock(return_value=()),
        add_invitation=add,
        notify=notify,
        enqueue_push=AsyncMock(),
    )
    case = ScheduleInvitations(repository(state))
    assert await case.execute(now) == 1
    assert await case.execute(now) == 0
    assert [event for event, _ in persisted] == ["invitation", "inbox"]
    assert persisted[0][1] is persisted[1][1]
    assert persisted[0][1].candidate_id == "daily_01"
    assert preference.next_due_at == now.replace(day=24, hour=20, minute=30)
    state.enqueue_push.assert_not_awaited()


@pytest.mark.anyio
async def test_expired_push_destination_is_disabled_without_replacing_terminal_result():
    now = datetime.now(UTC)
    owner, subscription_id, invitation_id, job_id, delivery_id = [uuid4() for _ in range(5)]
    invitation = Invitation(
        invitation_id,
        owner,
        "scheduled",
        now.date(),
        "UTC",
        now,
        now + timedelta(hours=1),
        "synthetic-occurrence",
        None,
        None,
        "generic",
        "daily_01",
        "general",
        "Synthetic question",
        "generic-v1",
        "1",
        now,
    )
    subscription = PushSubscription(
        subscription_id,
        owner,
        "https://push.example.test/opaque",
        "synthetic",
        "synthetic",
        uuid4(),
        "synthetic-session",
    )
    delivery = InvitationDelivery(delivery_id, owner, invitation_id, subscription_id, job_id)
    preference = InvitationPreference(owner, enabled=True)
    state = SimpleNamespace(
        delivery_context=AsyncMock(return_value=(preference, delivery, subscription)),
        invitation=AsyncMock(return_value=invitation),
        now=AsyncMock(return_value=now),
        cancel_deliveries=AsyncMock(),
    )
    transport = SimpleNamespace(
        send=AsyncMock(return_value=PushResult(expired=True, code="push_subscription_expired"))
    )
    context = SimpleNamespace(
        record=SimpleNamespace(user_id=owner, id=job_id, resource_id=delivery_id, stage_attempts=1),
        assert_lease=AsyncMock(),
    )
    await SendInvitation(repository(state), transport).execute(context)
    assert not subscription.active and delivery.status == "failed"
    state.cancel_deliveries.assert_awaited_once_with(owner, subscription_id)
    payload = transport.send.await_args.args[1]
    assert payload["binding_id"] == str(subscription.binding_id)
    assert payload["tag"] == f"invitation:{invitation_id}"
    assert context.assert_lease.await_count == 2


@pytest.mark.anyio
async def test_onboarding_skips_completed_action_and_does_not_reappear_after_enrollment():
    state = SimpleNamespace(
        now=AsyncMock(return_value=datetime.now(UTC)),
        enroll=AsyncMock(side_effect=[True, False]),
        progress=AsyncMock(return_value={"open_capture": True}),
        add=AsyncMock(),
    )
    owner = uuid4()
    case = NotificationCenter(repository(state))
    await case.bootstrap(owner)
    await case.bootstrap(owner)
    assert state.add.await_count == 2
    assert {call.kwargs["action"]["type"] for call in state.add.await_args_list} == {
        "open_install_help",
        "open_invitation_settings",
    }
    assert all(call.kwargs["owner"] == owner for call in state.add.await_args_list)


@pytest.mark.anyio
async def test_admin_metrics_keep_unknown_coverage_and_validate_period_before_querying():
    now = datetime.now(UTC)
    summary = SummaryFacts(
        now, 2, 1, None, None, None, {"writing": 20}, {}, None, False, None, False
    )
    activity = ActivityFacts(now, None, False, {}, {})
    store = SimpleNamespace(
        summary=AsyncMock(return_value=summary), activity=AsyncMock(return_value=activity)
    )
    case = Administration(store)
    result = await case.summary(7)
    assert result.notes_created is None and result.notes_by_source.writing is None
    assert result.users_accessed is None and result.users_wrote is None
    assert all(
        point.accessed is None and point.wrote is None for point in (await case.activity(7)).items
    )
    with pytest.raises(AdministrationError):
        await case.summary(14)
    store.summary.assert_awaited_once_with(7)


@pytest.mark.anyio
async def test_inventory_failure_invalidates_only_that_owner_and_continues_empty_accounts():
    first, second = uuid4(), uuid4()
    store = SimpleNamespace(
        guard=lambda: transaction(True),
        owners=AsyncMock(return_value=[first, second]),
        facts=AsyncMock(return_value=([], set())),
        invalidate=AsyncMock(),
        replace=AsyncMock(),
    )
    originals = SimpleNamespace(list=AsyncMock(side_effect=[ValueError("invalid_original"), None]))
    result = await SyncInventory(store, originals).run()
    assert result == {"status": "partial", "users": 2, "documents": 0, "failed": 1}
    store.invalidate.assert_awaited_once_with(first)
    store.replace.assert_awaited_once()
    assert store.replace.await_args.args[:2] == (second, [])


@pytest.mark.anyio
async def test_missing_accepted_original_never_becomes_a_successful_empty_inventory():
    owner = uuid4()
    receipt = ReceiptMetadata(uuid4(), "upload_document", datetime.now(UTC), False)
    store = SimpleNamespace(
        guard=lambda: transaction(True),
        owners=AsyncMock(return_value=[owner]),
        facts=AsyncMock(return_value=([receipt], set())),
        invalidate=AsyncMock(),
        replace=AsyncMock(),
    )
    result = await SyncInventory(store, SimpleNamespace(list=AsyncMock(return_value=[]))).run()
    assert result["failed"] == 1
    store.replace.assert_not_awaited()
    store.invalidate.assert_awaited_once_with(owner)
