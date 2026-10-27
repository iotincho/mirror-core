"""Resolve version priority and original reservation without mutating an extractor."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select

from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.adapters.storage.postgres.state import database_errors
from src.core.extractors.personal_axes.models import AxisWriteContext


class PostgresAxisWriteContexts:
    def __init__(self, sessions):
        self._sessions = sessions

    async def for_reservation(self, owner, processing_id, axis_id, version_id):
        async with database_errors(), self._sessions() as session:
            versions = dict(
                (
                    await session.execute(
                        select(PersonalAxisVersion.id, PersonalAxisVersion.number)
                        .join(PersonalAxis, PersonalAxis.id == PersonalAxisVersion.axis_id)
                        .where(PersonalAxis.id == UUID(str(axis_id)), PersonalAxis.user_id == owner)
                    )
                ).all()
            )
            number = versions.get(UUID(str(version_id)))
            if number is None:
                raise ValueError("axis_version_not_found")
            record = await session.get(ProcessingRecord, processing_id)
            if record is None or record.user_id != owner:
                raise ValueError("axis_reservation_not_found")
            reservation = record
            if record.parent_processing_id:
                reservation = await session.get(ProcessingRecord, record.parent_processing_id)
                if reservation is None or reservation.user_id != owner:
                    raise ValueError("axis_parent_not_found")
            stamp = reservation.created_at.astimezone(UTC).isoformat(timespec="microseconds")
            return AxisWriteContext(
                f"{number:012d}:{stamp}:{reservation.id}",
                tuple((str(key), value) for key, value in versions.items()),
            )
