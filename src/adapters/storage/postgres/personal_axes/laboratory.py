"""Account-owned Laboratory grant and monotonic welcome preference."""

from sqlalchemy import func, select, update

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.personal_axes.boundaries import axis_database_call
from src.core.extractors.personal_axes.definitions import LaboratoryState


class PostgresLaboratory:
    def __init__(self, sessions=None, *, session=None):
        self.sessions, self.session = sessions, session

    @axis_database_call
    async def read(self, owner):
        if self.session is not None:
            return await self._read(self.session, owner)
        async with self.sessions() as session:
            return await self._read(session, owner)

    async def _read(self, session, owner):
        row = (
            await session.execute(
                select(
                    User.is_active, User.laboratory_enabled, User.laboratory_welcome_dismissed_at
                ).where(User.id == owner)
            )
        ).first()
        return (
            LaboratoryState(active=row[0], granted=row[1], welcome_dismissed=row[2] is not None)
            if row
            else LaboratoryState()
        )

    @axis_database_call
    async def dismiss_welcome(self, owner):
        if self.session is not None:
            await self._dismiss(self.session, owner)
            await self.session.commit()
        else:
            async with self.sessions.begin() as session:
                await self._dismiss(session, owner)

    async def _dismiss(self, session, owner):
        await session.execute(
            update(User)
            .where(User.id == owner, User.laboratory_welcome_dismissed_at.is_(None))
            .values(laboratory_welcome_dismissed_at=func.now())
        )
