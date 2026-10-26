"""Compose opt-in foreground observations without opening content or workspace clients."""

from src.adapters.storage.postgres.activity import PostgresActivity
from src.bootstrap.database import get_session_maker
from src.bootstrap.settings import get_settings
from src.use_cases.administration.record_access import RecordAccess


def get_record_access():
    return RecordAccess(
        PostgresActivity(get_session_maker()), enabled=get_settings().platform_activity_enabled
    )


async def record_access(sessions, user_id, now=None):
    return await RecordAccess(PostgresActivity(sessions)).execute(user_id, now)
