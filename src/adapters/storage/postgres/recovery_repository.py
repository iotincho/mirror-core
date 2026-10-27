"""PostgreSQL transactions and locks shared by API, workers and cleanup."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.recovery_models import RecoveryAddress, RecoveryIP
from src.adapters.storage.postgres.recovery_transaction import RecoveryTransaction
from src.adapters.storage.postgres.state import database_errors
from src.core.auth.recovery import RecoveryError as RecoveryError


class RecoveryRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def now(self, session) -> datetime:
        return await session.scalar(select(func.clock_timestamp()))

    async def ip(self, session, key):
        await session.execute(insert(RecoveryIP).values(key=key).on_conflict_do_nothing())
        return await session.get(RecoveryIP, key, with_for_update=True)

    async def address(self, session, key):
        await session.execute(insert(RecoveryAddress).values(key=key).on_conflict_do_nothing())
        return await session.get(RecoveryAddress, key, with_for_update=True)

    async def cleanup(self):
        async with self.sessions.begin() as session:
            now = await self.now(session)
            addresses = await session.scalars(
                select(RecoveryAddress)
                .where(
                    RecoveryAddress.expires_at <= now,
                    RecoveryAddress.code_ciphertext.is_not(None),
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
            for address in addresses:
                address.code_ciphertext = address.code_mac = None
            await session.execute(
                delete(RecoveryIP).where(RecoveryIP.updated_at < now - timedelta(days=1))
            )
            await session.execute(
                delete(RecoveryAddress).where(RecoveryAddress.updated_at < now - timedelta(days=2))
            )

    @asynccontextmanager
    async def transaction(self):
        async with database_errors(), self.sessions.begin() as session:
            transaction = RecoveryTransaction(self, session)
            yield transaction
            transaction.synchronize()
