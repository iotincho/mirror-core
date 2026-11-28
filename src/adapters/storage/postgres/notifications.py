"""Owner-scoped inbox predicates and atomic publication/fan-out storage."""

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import String, Uuid, case, cast, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationPreference,
    InvitationResponse,
)
from src.adapters.storage.postgres.models import ProcessingReceipt
from src.adapters.storage.postgres.notification_models import (
    Announcement,
    Notification,
    NotificationEnrollment,
)
from src.adapters.storage.postgres.snapshots import SnapshotTracker
from src.adapters.storage.postgres.state import database_errors
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.notifications.models import DEFAULT_LIFETIME_DAYS, NotificationRead
from src.core.notifications.states import AnnouncementState


def available_until():
    response = select(InvitationResponse.document_id).where(
        InvitationResponse.user_id == Invitation.user_id,
        InvitationResponse.invitation_id == Invitation.id,
    )
    accepted_upload = select(ProcessingReceipt.id).where(
        ProcessingReceipt.user_id == Invitation.user_id,
        ProcessingReceipt.operation.in_(["upload_document", "upload_audio"]),
        ProcessingReceipt.is_original.is_(True),
        ProcessingReceipt.accepted_at.is_not(None),
        ProcessingReceipt.manifest["invitation_id"].astext == cast(Invitation.id, String),
    )
    invitation_expiry = (
        select(Invitation.expires_at)
        .where(
            Invitation.user_id == Notification.user_id,
            Invitation.id == cast(Notification.action["invitation_id"].as_string(), Uuid),
            ~response.exists(),
            ~accepted_upload.exists(),
        )
        .correlate(Notification)
        .scalar_subquery()
    )
    return case(
        (Notification.kind == "invitation", invitation_expiry), else_=Notification.expires_at
    )


def visible(owner, now, expires_at):
    return (
        Notification.user_id == owner,
        Notification.published_at <= now,
        Notification.created_at <= now,
        expires_at > now,
        Notification.dismissed_at.is_(None),
    )


async def add_notification(
    session, *, owner, key, kind, title, summary, body, action, now, expires_at=None, read_at=None
):
    await session.execute(
        insert(Notification)
        .values(
            id=uuid4(),
            user_id=owner,
            deduplication_key=key,
            kind=kind,
            title=title,
            summary=summary,
            body=body,
            action=action,
            published_at=now,
            expires_at=expires_at or now + timedelta(days=DEFAULT_LIFETIME_DAYS),
            read_at=read_at,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "deduplication_key"])
    )


class PostgresNotifications:
    def __init__(self, sessions):
        self.sessions = sessions

    async def now(self, session):
        return await session.scalar(select(func.clock_timestamp()))

    @asynccontextmanager
    async def transaction(self):
        async with database_errors(), self.sessions.begin() as session:
            transaction = NotificationTransaction(self, session)
            yield transaction
            transaction.synchronize()


class NotificationTransaction(SnapshotTracker):
    def __init__(self, repository, session):
        super().__init__()
        self.repository, self.session = repository, session

    async def now(self):
        return await self.repository.now(self.session)

    async def progress(self, owner):
        first_note = await self.session.scalar(
            select(ProcessingReceipt.id)
            .where(
                ProcessingReceipt.user_id == owner,
                ProcessingReceipt.accepted_at.is_not(None),
                ProcessingReceipt.operation.in_(
                    ["upload_document", "upload_audio", "import_document"]
                ),
            )
            .limit(1)
        )
        daily = await self.session.scalar(
            select(InvitationPreference.enabled).where(
                InvitationPreference.user_id == owner,
            )
        )
        return {"open_capture": first_note is not None, "open_invitation_settings": bool(daily)}

    async def enroll(self, owner, now):
        return (
            await self.session.scalar(
                insert(NotificationEnrollment)
                .values(
                    user_id=owner,
                    initialized_at=now,
                )
                .on_conflict_do_nothing()
                .returning(NotificationEnrollment.user_id)
            )
            is not None
        )

    async def add(self, **notice):
        await add_notification(self.session, **notice)

    async def count(self, owner, now):
        return await self.session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                *visible(owner, now, available_until()),
                Notification.read_at.is_(None),
            )
        )

    async def page(self, owner, now, cursor, unread_only, limit):
        expires_at = available_until()
        query = select(Notification, expires_at).where(*visible(owner, now, expires_at))
        unread = Notification.read_at.is_(None)
        if unread_only:
            query = query.where(unread)
        if cursor is not None:
            query = query.where(tuple_(unread, Notification.published_at, Notification.id) < cursor)
        rows = await self.session.execute(
            query.order_by(
                unread.desc(),
                Notification.published_at.desc(),
                Notification.id.desc(),
            ).limit(limit)
        )
        return [
            NotificationRead.model_validate(row).model_copy(update={"expires_at": expiry})
            for row, expiry in rows
        ]

    async def mark(self, owner, identifier, dismiss, now):
        column = Notification.dismissed_at if dismiss else Notification.read_at
        found = await self.session.scalar(
            update(Notification)
            .where(
                Notification.user_id == owner,
                Notification.id == identifier,
            )
            .values({column: func.coalesce(column, now)})
            .returning(Notification.id)
        )
        return found is not None

    async def read_all(self, owner, through, now):
        await self.session.execute(
            update(Notification)
            .where(
                *visible(owner, now, available_until()),
                Notification.published_at <= through,
                Notification.created_at <= through,
                Notification.read_at.is_(None),
            )
            .values(read_at=now)
        )

    @staticmethod
    def audience(published_at):
        return (
            select(User.id)
            .join(UserWorkspace)
            .where(
                User.is_active.is_(True),
                UserWorkspace.status == "active",
                or_(User.created_at.is_(None), User.created_at <= published_at),
            )
        )

    async def audience_count(self, published_at):
        return await self.session.scalar(
            select(func.count()).select_from(
                self.audience(published_at).subquery(),
            )
        )

    async def reserve_publication(self, content, now, expires_at):
        snapshot = content.model_dump(mode="json")
        await self.session.execute(
            insert(Announcement)
            .values(
                key=content.key,
                content=snapshot,
                published_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing()
        )
        return self.track(await self.session.get(Announcement, content.key), AnnouncementState)

    async def publications(self):
        rows = await self.session.scalars(
            select(Announcement)
            .where(
                Announcement.finished_at.is_(None),
            )
            .order_by(Announcement.published_at)
            .limit(5)
            .with_for_update(skip_locked=True)
        )
        return [self.track(row, AnnouncementState) for row in rows]

    async def recipients(self, published_at, after, limit):
        query = self.audience(published_at)
        if after:
            query = query.where(User.id > after)
        return list((await self.session.scalars(query.order_by(User.id).limit(limit))).all())
