"""Read-only SQL liveness check without exposing SQL to the HTTP adapter."""

from sqlalchemy import text

from src.adapters.storage.postgres.boundaries import database_call


class PostgresHealth:
    def __init__(self, sessions):
        self.sessions = sessions

    @database_call
    async def check(self):
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))
