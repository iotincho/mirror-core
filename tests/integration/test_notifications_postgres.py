"""Run against an isolated, migrated PostgreSQL database only."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import Invitation, InvitationPreference
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.adapters.storage.postgres.notification_models import Announcement, Notification
from src.adapters.storage.postgres.notifications import add_notification
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.notifications import build_notification_center as NotificationRepository
from src.bootstrap.notifications import get_notifications
from src.bootstrap.public_api import app
from src.core.notifications.models import AnnouncementContent
from src.core.notifications.rules import NotificationError
from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("NOTIFICATIONS_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def inbox():
    engine = create_async_engine(
        os.environ["NOTIFICATIONS_TEST_DATABASE_URL"], hide_parameters=True
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owners = [uuid4(), uuid4()]
    async with sessions.begin() as session:
        for owner in owners:
            session.add(User(id=owner, email=f"{owner}@example.test", hashed_password="unused"))
            await session.flush()
            session.add(
                UserWorkspace(
                    user_id=owner,
                    arcadedb_instance_key="test",
                    database_name=f"test_{owner.hex}",
                    graph_username=f"test_{owner.hex}",
                    graph_secret_ciphertext="unused",
                    status="active",
                )
            )
    repository = NotificationRepository(sessions)
    yield repository, owners
    app.dependency_overrides.clear()
    async with sessions.begin() as session:
        await session.execute(delete(Invitation).where(Invitation.user_id.in_(owners)))
        await session.execute(delete(User).where(User.id.in_(owners)))
    await engine.dispose()


async def add(repository, owner, key, now=None, **options):
    async with repository.store.sessions.begin() as session:
        await add_notification(
            session,
            owner=owner,
            key=key,
            kind="announcement",
            title=key,
            summary="A summary",
            body="Plain text content",
            action=None,
            now=now or await repository.store.now(session),
            **options,
        )


async def test_bootstrap_concurrent_once_and_default_expiry(inbox):
    repository, (owner, _) = inbox
    await asyncio.gather(*(repository.bootstrap(owner) for _ in range(4)))
    page = await repository.list(owner)
    assert len(page.items) == page.unread_count == 3
    assert all(item.expires_at - item.published_at == timedelta(days=15) for item in page.items)
    await repository.mutate(owner, page.items[0].id, dismiss=True)
    await repository.bootstrap(owner)
    assert len((await repository.list(owner)).items) == 2
    async with repository.store.sessions.begin() as session:
        await session.execute(
            update(Notification)
            .where(Notification.user_id == owner)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await repository.bootstrap(owner)
    assert (await repository.summary(owner))["unread_count"] == 0
    assert (await repository.list(owner)).items == []


async def test_stable_pagination_ownership_read_and_expiry(inbox):
    repository, (owner, stranger) = inbox
    now = datetime.now(UTC) - timedelta(seconds=2)
    for index in range(6):
        await add(repository, owner, str(index), now)
    await add(repository, stranger, "other-account", now)
    await add(repository, owner, "expired", now, expires_at=now)
    first = await repository.list(owner, limit=3)
    await add(repository, owner, "new-between-pages")
    await add(repository, owner, "late-delivery-with-old-date", now + timedelta(seconds=1))
    second = await repository.list(owner, first.next_cursor, limit=3)
    assert len({item.id for item in first.items + second.items}) == 6
    assert second.next_cursor is None
    target = first.items[0]
    with pytest.raises(NotificationError) as failure:
        await repository.mutate(stranger, target.id)
    assert failure.value.code == "notification_not_found"
    await asyncio.gather(repository.mutate(owner, target.id), repository.mutate(owner, target.id))
    read = next(item for item in (await repository.list(owner)).items if item.id == target.id)
    await repository.mutate(owner, target.id)
    assert (
        next(item for item in (await repository.list(owner)).items if item.id == target.id).read_at
        == read.read_at
    )
    await repository.read_all(owner, first.through)
    unread = await repository.list(owner, unread_only=True)
    assert {item.title for item in unread.items} == {
        "new-between-pages",
        "late-delivery-with-old-date",
    }
    assert unread.unread_count == 2
    assert (await repository.summary(stranger))["unread_count"] == 1


async def test_unread_first_across_pages_then_newest_within_each_group(inbox):
    repository, (owner, _) = inbox
    now = datetime.now(UTC)
    for index in range(1, 6):
        await add(
            repository,
            owner,
            str(index),
            now - timedelta(minutes=index),
            read_at=now if index <= 2 else None,
        )
    first = await repository.list(owner, limit=2)
    second = await repository.list(owner, first.next_cursor, limit=2)
    third = await repository.list(owner, second.next_cursor, limit=2)
    assert [item.title for item in first.items + second.items + third.items] == [
        "3",
        "4",
        "5",
        "1",
        "2",
    ]
    assert third.next_cursor is None
    assert len({item.id for item in first.items + second.items + third.items}) == 5
    await repository.mutate(owner, first.items[0].id)
    fresh = await repository.list(owner)
    assert [item.title for item in fresh.items] == ["4", "5", "1", "2", "3"]
    await repository.read_all(owner, fresh.through)
    all_read = await repository.list(owner)
    assert [item.title for item in all_read.items] == ["1", "2", "3", "4", "5"]
    assert all_read.unread_count == 0
    assert all(item.read_at for item in all_read.items)


async def test_daily_without_push_and_opening_marks_inbox_read(inbox):
    repository, (owner, _) = inbox
    invitations = InvitationRepository(repository.store.sessions)
    service = ConfigureInvitations(invitations)
    await service.configure(owner, True, "20:30", "UTC")
    now = datetime.now(UTC)
    async with repository.store.sessions.begin() as session:
        preference = await session.get(InvitationPreference, owner)
        preference.local_time = now.strftime("%H:%M")
        preference.next_due_at = now - timedelta(seconds=1)
    counts = await asyncio.gather(
        *(ScheduleInvitations(invitations).execute(now) for _ in range(3))
    )
    assert sum(counts) == 1
    page = await repository.list(owner)
    assert len(page.items) == 1
    item = page.items[0]
    invitation = await service.get_invitation(owner, item.action.invitation_id)
    assert invitation.question == item.body == item.summary
    assert item.expires_at - item.published_at == timedelta(days=1)
    # A transport TTL of two hours does not expire the inbox action.
    async with repository.store.sessions.begin() as session:
        await session.execute(
            update(Invitation)
            .where(Invitation.id == invitation.id)
            .values(expires_at=now - timedelta(minutes=1))
        )
    await service.open_invitation(owner, invitation.id)
    assert (await repository.summary(owner))["unread_count"] == 0
    assert (await repository.list(owner)).items[0].read_at is not None


async def test_onboarding_completion_is_distinct_from_reading(inbox):
    repository, (owner, _) = inbox
    await repository.bootstrap(owner)
    daily = next(
        item
        for item in (await repository.list(owner)).items
        if item.action.type == "open_invitation_settings"
    )
    await repository.mutate(owner, daily.id)
    assert not next(
        item for item in (await repository.list(owner)).items if item.id == daily.id
    ).completed
    await ConfigureInvitations(InvitationRepository(repository.store.sessions)).configure(
        owner, True, "20:30", "UTC"
    )
    assert next(
        item for item in (await repository.list(owner)).items if item.id == daily.id
    ).completed


async def test_restartable_publication_deduplicates_and_snapshots_content(inbox):
    repository, owners = inbox
    key = f"test-{uuid4().hex}"
    content = AnnouncementContent(
        key=key, title="New feature", summary="Discover it", body="Details"
    )
    try:
        await repository.publish(content)
        await repository.publish(content)
        with pytest.raises(ValueError, match="different content"):
            await repository.publish(content.model_copy(update={"body": "Mutated"}))
        # Simulate multiple dispatcher replicas and repeated batches.
        for _ in range(4):
            await asyncio.gather(repository.distribute(limit=1), repository.distribute(limit=1))
        for owner in owners:
            page = await repository.list(owner)
            assert len(page.items) == 1
            assert page.items[0].body == "Details"
            assert page.items[0].expires_at - page.items[0].published_at == timedelta(days=15)
        async with repository.store.sessions() as session:
            assert (await session.get(Announcement, key)).finished_at is not None
    finally:
        async with repository.store.sessions.begin() as session:
            await session.execute(delete(Announcement).where(Announcement.key == key))


async def test_http_contract_origin_and_invalid_cursor(inbox):
    repository, (owner, stranger) = inbox
    app.dependency_overrides[get_notifications] = lambda: repository
    app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(id=owner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://inbox.test"
    ) as client:
        assert (await client.post("/notifications/bootstrap")).status_code == 204
        page = (await client.get("/notifications")).json()
        assert page["unread_count"] == 3
        assert (await client.get("/notifications?cursor=invalid")).status_code == 422
        assert (
            await client.post("/notifications/read-all", json={"through": "2030-01-01T00:00:00Z"})
        ).status_code == 422
        assert (
            await client.post(
                "/notifications/read-all",
                json={"through": page["through"]},
                headers={"sec-fetch-site": "cross-site"},
            )
        ).status_code == 403
        app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(id=stranger)
        assert (
            await client.post(f"/notifications/{page['items'][0]['id']}/read")
        ).status_code == 404
        app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(id=owner)
        assert (
            await client.post("/notifications/read-all", json={"through": page["through"]})
        ).status_code == 204
        assert (await client.get("/notifications/summary")).json()["unread_count"] == 0


async def test_notification_insert_and_domain_change_rollback_together(inbox):
    repository, (owner, _) = inbox
    with pytest.raises(RuntimeError):
        async with repository.store.sessions.begin() as session:
            await add_notification(
                session,
                owner=owner,
                key="rollback",
                kind="announcement",
                title="Rollback",
                summary="Rollback",
                body="Rollback",
                action=None,
                now=await repository.store.now(session),
            )
            raise RuntimeError("simulated crash before commit")
    async with repository.store.sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Notification).where(Notification.user_id == owner)
            )
            == 0
        )
