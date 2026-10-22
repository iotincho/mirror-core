"""Order active writes by accepted version and reservation, independent of completion."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select

from src.extractors.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.processing.models import ProcessingRecord


async def bind_axis_write(extractor, sessions, record):
    spec = record.config["extractor"]
    async with sessions() as session:
        versions = dict(
            (
                await session.execute(
                    select(PersonalAxisVersion.id, PersonalAxisVersion.number)
                    .join(PersonalAxis, PersonalAxis.id == PersonalAxisVersion.axis_id)
                    .where(
                        PersonalAxis.id == UUID(spec["axis_id"]),
                        PersonalAxis.user_id == record.user_id,
                    )
                )
            ).all()
        )
        number = versions.get(UUID(spec["version_id"]))
        if number is None:
            raise ValueError("axis_version_not_found")
        reservation = record
        if record.parent_processing_id:
            parent = await session.get(ProcessingRecord, record.parent_processing_id)
            if parent is None or parent.user_id != record.user_id:
                raise ValueError("axis_parent_not_found")
            reservation = parent
    stamp = reservation.created_at.astimezone(UTC).isoformat(timespec="microseconds")
    extractor.write_order = f"{number:012d}:{stamp}:{reservation.id}"
    extractor.legacy_versions = {str(key): value for key, value in versions.items()}
