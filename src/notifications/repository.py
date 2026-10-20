"""Inbox queries and mutations always share the same owner/visibility predicate."""

import base64
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from src.exteriorization.models import InvitationPreference
from src.notifications.models import Announcement, Notification, NotificationEnrollment
from src.notifications.schemas import (
    DEFAULT_LIFETIME_DAYS,
    AnnouncementContent,
    NotificationList,
    NotificationRead,
)
from src.processing.models import ProcessingReceipt
from src.user_management.models import User
from src.workspaces.models import UserWorkspace

ONBOARDING = (
    (
        "first-note",
        "Dale lugar a tu primera reflexión",
        "Escribí o grabá algo, a tu manera.",
        "No hace falta encontrar las palabras perfectas. Una idea o unos segundos de voz alcanzan.",
        "open_capture",
    ),
    (
        "install",
        "Tu espacio, más cerca",
        "Instalá El Espejo en este dispositivo.",
        "Podés agregar El Espejo a tu pantalla de inicio. "
        "Es opcional y podés hacerlo cuando quieras.",
        "open_install_help",
    ),
    (
        "daily",
        "Una pregunta para encontrar por dónde empezar",
        "Elegí si querés una pregunta diaria.",
        "La pregunta estará en la app. "
        "Si querés, también podés recibir un aviso en este dispositivo.",
        "open_invitation_settings",
    ),
)


def visible(owner, now):
    return (
        Notification.user_id == owner,
        Notification.published_at <= now,
        Notification.created_at <= now,
        Notification.expires_at > now,
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


def encode_cursor(item):
    return base64.urlsafe_b64encode(
        json.dumps([item.read_at is None, item.published_at.isoformat(), str(item.id)]).encode()
    ).decode()


def decode_cursor(cursor):
    try:
        if len(cursor) > 300:
            raise ValueError()
        raw = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or not isinstance(raw[0], bool)
            or not all(isinstance(item, str) for item in raw[1:])
        ):
            raise ValueError()
        unread, when, identifier = raw
        when = datetime.fromisoformat(when)
        if when.tzinfo is None:
            raise ValueError()
        return unread, when, UUID(identifier)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "invalid_notification_cursor") from None


class NotificationRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def now(self, session):
        return await session.scalar(select(func.clock_timestamp()))

    async def progress(self, session, owner):
        first_note = await session.scalar(
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
        daily = await session.scalar(
            select(InvitationPreference.enabled).where(InvitationPreference.user_id == owner)
        )
        return {"open_capture": first_note is not None, "open_invitation_settings": bool(daily)}

    async def bootstrap(self, owner):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            inserted = await session.scalar(
                insert(NotificationEnrollment)
                .values(
                    user_id=owner,
                    initialized_at=now,
                )
                .on_conflict_do_nothing()
                .returning(NotificationEnrollment.user_id)
            )
            if inserted is None:
                return
            progress = await self.progress(session, owner)
            for key, title, summary, body, action in ONBOARDING:
                if progress.get(action):
                    continue
                await add_notification(
                    session,
                    owner=owner,
                    key=f"onboarding:v1:{key}",
                    kind="onboarding",
                    title=title,
                    summary=summary,
                    body=body,
                    action={"type": action},
                    now=now,
                )

    async def count(self, session, owner, now):
        return await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(*visible(owner, now), Notification.read_at.is_(None))
        )

    async def summary(self, owner):
        async with self.sessions() as session:
            return {"unread_count": await self.count(session, owner, await self.now(session))}

    async def list(self, owner, cursor=None, unread_only=False, limit=30):
        async with self.sessions() as session:
            now = await self.now(session)
            query = select(Notification).where(*visible(owner, now))
            unread = Notification.read_at.is_(None)
            if unread_only:
                query = query.where(Notification.read_at.is_(None))
            if cursor:
                query = query.where(
                    tuple_(unread, Notification.published_at, Notification.id)
                    < decode_cursor(cursor)
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(
                            unread.desc(), Notification.published_at.desc(), Notification.id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            progress = await self.progress(session, owner)
            items = [
                NotificationRead.model_validate(row).model_copy(
                    update={
                        "completed": row.kind == "onboarding"
                        and progress.get((row.action or {}).get("type"), False)
                    }
                )
                for row in rows[:limit]
            ]
            return NotificationList(
                items=items,
                next_cursor=encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
                unread_count=await self.count(session, owner, now),
                through=now,
            )

    async def mutate(self, owner, identifier, *, dismiss=False):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            column = Notification.dismissed_at if dismiss else Notification.read_at
            # Expired/dismissed rows stay addressable for idempotent retries by their owner.
            found = await session.scalar(
                update(Notification)
                .where(
                    Notification.user_id == owner,
                    Notification.id == identifier,
                )
                .values({column: func.coalesce(column, now)})
                .returning(Notification.id)
            )
            if found is None:
                raise HTTPException(404, "notification_not_found")

    async def read_all(self, owner, through):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            if through > now:
                raise HTTPException(422, "future_notification_cutoff")
            await session.execute(
                update(Notification)
                .where(
                    *visible(owner, now),
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

    async def preview(self):
        async with self.sessions() as session:
            return await session.scalar(
                select(func.count()).select_from(self.audience(await self.now(session)).subquery())
            )

    async def publish(self, content: AnnouncementContent):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            snapshot = content.model_dump(mode="json")
            await session.execute(
                insert(Announcement)
                .values(
                    key=content.key,
                    content=snapshot,
                    published_at=now,
                    expires_at=now + timedelta(days=content.lifetime_days),
                )
                .on_conflict_do_nothing()
            )
            existing = await session.get(Announcement, content.key)
            if existing.content != snapshot:
                raise ValueError("Publication key already exists with different content")

    async def distribute(self, limit=100):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            publications = (
                await session.scalars(
                    select(Announcement)
                    .where(Announcement.finished_at.is_(None))
                    .order_by(Announcement.published_at)
                    .limit(5)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for publication in publications:
                if publication.expires_at <= now:
                    publication.finished_at = now
                    continue
                query = self.audience(publication.published_at)
                if publication.last_user_id:
                    query = query.where(User.id > publication.last_user_id)
                owners = list((await session.scalars(query.order_by(User.id).limit(limit))).all())
                content = AnnouncementContent.model_validate(publication.content)
                for owner in owners:
                    await add_notification(
                        session,
                        owner=owner,
                        key=f"announcement:{publication.key}",
                        kind="announcement",
                        title=content.title,
                        summary=content.summary,
                        body=content.body,
                        action=content.action.model_dump(mode="json") if content.action else None,
                        now=publication.published_at,
                        expires_at=publication.expires_at,
                    )
                if owners:
                    publication.last_user_id = owners[-1]
                if len(owners) < limit:
                    publication.finished_at = now
