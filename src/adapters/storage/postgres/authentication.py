"""Account row locking shared by FastAPI Users login and recovery."""

from sqlalchemy import func, select
from sqlalchemy.orm import noload

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.snapshots import SnapshotTracker
from src.core.auth.identity import AccountCredentials


class PostgresAuthentication:
    def __init__(self, user_database):
        self.database = user_database
        self.user = None

    async def credentials(self, email):
        self.user = await self.database.session.scalar(
            select(User)
            .options(noload(User.oauth_accounts))
            .where(func.lower(User.email) == email.lower())
            .with_for_update(of=User, key_share=True)
        )
        return SnapshotTracker().track(self.user, AccountCredentials)

    async def confirm_login(self, account, changes):
        self.user = await self.database.update(self.user, changes)
        for name, value in changes.items():
            setattr(account, name, value)
