"""Read session/workspace facts and release the connection before streaming."""

from datetime import timedelta

import anyio
from sqlalchemy import func, select

from src.adapters.storage.postgres.accounts import AccessToken, User
from src.adapters.storage.postgres.boundaries import database_call
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.auth.session import SessionOwner


class PostgresStreamSessions:
    def __init__(self, sessions, ttl_seconds):
        self.sessions, self.ttl_seconds = sessions, ttl_seconds

    @database_call
    async def lookup(self, token):
        with anyio.CancelScope(shield=True):
            async with self.sessions() as session:
                row = (
                    await session.execute(
                        select(User.id, UserWorkspace.status, UserWorkspace.arcadedb_instance_key)
                        .join(AccessToken, AccessToken.user_id == User.id)
                        .outerjoin(UserWorkspace, UserWorkspace.user_id == User.id)
                        .where(
                            AccessToken.token == token,
                            User.is_active.is_(True),
                            AccessToken.created_at
                            >= func.clock_timestamp() - timedelta(seconds=self.ttl_seconds),
                        )
                    )
                ).first()
                return SessionOwner(row.id, row.status, row.arcadedb_instance_key) if row else None
