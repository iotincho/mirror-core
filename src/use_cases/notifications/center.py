"""Inbox/onboarding and explicit publication policy over one transactional port."""

from datetime import timedelta

from src.core.notifications.models import AnnouncementContent, NotificationList
from src.core.notifications.ports import Notifications
from src.core.notifications.rules import ONBOARDING, NotificationError, decode_cursor, encode_cursor


class NotificationCenter:
    def __init__(self, store: Notifications):
        self.store = store

    async def bootstrap(self, owner):
        async with self.store.transaction() as transaction:
            now = await transaction.now()
            if not await transaction.enroll(owner, now):
                return
            progress = await transaction.progress(owner)
            for key, title, summary, body, action in ONBOARDING:
                if not progress.get(action):
                    await transaction.add(
                        owner=owner,
                        key=f"onboarding:v1:{key}",
                        kind="onboarding",
                        title=title,
                        summary=summary,
                        body=body,
                        action={"type": action},
                        now=now,
                    )

    async def summary(self, owner):
        async with self.store.transaction() as transaction:
            return {"unread_count": await transaction.count(owner, await transaction.now())}

    async def list(self, owner, cursor=None, unread_only=False, limit=30):
        position = decode_cursor(cursor) if cursor else None
        async with self.store.transaction() as transaction:
            now = await transaction.now()
            rows = await transaction.page(owner, now, position, unread_only, limit + 1)
            progress = await transaction.progress(owner)
            items = [
                row.model_copy(
                    update={
                        "completed": row.kind == "onboarding"
                        and progress.get((row.action.type if row.action else None), False),
                    }
                )
                for row in rows[:limit]
            ]
            return NotificationList(
                items=items,
                next_cursor=encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
                unread_count=await transaction.count(owner, now),
                through=now,
            )

    async def mutate(self, owner, identifier, *, dismiss=False):
        async with self.store.transaction() as transaction:
            if not await transaction.mark(owner, identifier, dismiss, await transaction.now()):
                raise NotificationError("notification_not_found")

    async def read_all(self, owner, through):
        async with self.store.transaction() as transaction:
            now = await transaction.now()
            if through > now:
                raise NotificationError("future_notification_cutoff")
            await transaction.read_all(owner, through, now)

    async def preview(self):
        async with self.store.transaction() as transaction:
            return await transaction.audience_count(await transaction.now())

    async def publish(self, content: AnnouncementContent):
        async with self.store.transaction() as transaction:
            now = await transaction.now()
            publication = await transaction.reserve_publication(
                content,
                now,
                now + timedelta(days=content.lifetime_days),
            )
            if publication.content != content.model_dump(mode="json"):
                raise ValueError("Publication key already exists with different content")

    async def distribute(self, limit=100):
        async with self.store.transaction() as transaction:
            now = await transaction.now()
            for publication in await transaction.publications():
                if publication.expires_at <= now:
                    publication.finished_at = now
                    continue
                owners = await transaction.recipients(
                    publication.published_at, publication.last_user_id, limit
                )
                content = AnnouncementContent.model_validate(publication.content)
                for owner in owners:
                    await transaction.add(
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
