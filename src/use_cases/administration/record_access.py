"""Opt-in foreground observations with fixed local-day aggregation and retention."""

from datetime import UTC, datetime, timedelta

from src.core.administration.ports import ActivityStore
from src.core.administration.rules import ZONE


class RecordAccess:
    def __init__(self, store: ActivityStore, *, enabled=True):
        self.store, self.enabled = store, enabled

    async def execute(self, user_id, now=None):
        if not self.enabled:
            return
        now = now or datetime.now(UTC)
        day = now.astimezone(ZONE).date()
        await self.store.observe(user_id, day, now, day - timedelta(days=90))
