"""Ownership and transactional approval of immutable definitions."""

from uuid import uuid4

from sqlalchemy import func, select

from src.extractors.personal_axes.contracts import AxisError
from src.extractors.personal_axes.models import PersonalAxis, PersonalAxisVersion


def axis_response(axis, version):
    return {
        "id": str(axis.id),
        "enabled": axis.enabled,
        "current_version_id": str(axis.current_version_id),
        "version": {
            "id": str(version.id),
            "number": version.number,
            "title": version.title,
            "purpose": version.purpose,
            "specification": version.specification,
            "specification_hash": version.specification_hash,
            "created_at": version.created_at.isoformat(),
        },
    }


class AxisRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def approved(self, owner, preview_id, revision_hash):
        async with self.sessions() as session:
            pair = (
                await session.execute(
                    select(PersonalAxis, PersonalAxisVersion)
                    .join(PersonalAxisVersion, PersonalAxisVersion.axis_id == PersonalAxis.id)
                    .where(
                        PersonalAxis.user_id == owner,
                        PersonalAxisVersion.accepted_preview_id == preview_id,
                    )
                )
            ).first()
            if pair is None:
                return None
            if pair[1].revision_hash != revision_hash:
                raise AxisError("axis_revision_conflict")
            return axis_response(*pair)

    async def get(self, owner, axis_id):
        async with self.sessions() as session:
            pair = (
                await session.execute(
                    select(PersonalAxis, PersonalAxisVersion)
                    .join(
                        PersonalAxisVersion,
                        PersonalAxis.current_version_id == PersonalAxisVersion.id,
                    )
                    .where(PersonalAxis.id == axis_id, PersonalAxis.user_id == owner)
                )
            ).first()
            if pair is None:
                raise AxisError("axis_not_found", 404)
            return axis_response(*pair)

    async def list(self, owner, offset=0, limit=50):
        async with self.sessions() as session:
            pairs = (
                await session.execute(
                    select(PersonalAxis, PersonalAxisVersion)
                    .join(
                        PersonalAxisVersion,
                        PersonalAxis.current_version_id == PersonalAxisVersion.id,
                    )
                    .where(PersonalAxis.user_id == owner)
                    .order_by(PersonalAxis.created_at.desc(), PersonalAxis.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            return {
                "items": [axis_response(*pair) for pair in pairs[:limit]],
                "next_offset": offset + limit if len(pairs) > limit else None,
            }

    async def version(self, owner, axis_id, version_id):
        async with self.sessions() as session:
            pair = (
                await session.execute(
                    select(PersonalAxis, PersonalAxisVersion)
                    .join(PersonalAxisVersion, PersonalAxisVersion.axis_id == PersonalAxis.id)
                    .where(
                        PersonalAxis.user_id == owner,
                        PersonalAxis.id == axis_id,
                        PersonalAxisVersion.id == version_id,
                    )
                )
            ).first()
            if pair is None:
                raise AxisError("axis_version_not_found", 404)
            return axis_response(*pair)

    async def set_enabled(self, owner, axis_id, enabled):
        async with self.sessions.begin() as session:
            axis = await session.scalar(
                select(PersonalAxis)
                .where(PersonalAxis.id == axis_id, PersonalAxis.user_id == owner)
                .with_for_update()
            )
            if axis is None:
                raise AxisError("axis_not_found", 404)
            axis.enabled = enabled
            axis.updated_at = await session.scalar(select(func.clock_timestamp()))
        return await self.get(owner, axis_id)

    async def accept(self, owner, preview_id, request, specification, expires_at):
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            if now >= expires_at:
                raise AxisError("axis_preview_expired", 410)
            if request.axis_id:
                axis = await session.scalar(
                    select(PersonalAxis)
                    .where(PersonalAxis.id == request.axis_id, PersonalAxis.user_id == owner)
                    .with_for_update()
                )
                if axis is None:
                    raise AxisError("axis_not_found", 404)
                if axis.current_version_id != request.base_version_id:
                    raise AxisError("axis_base_version_conflict")
                current = await session.get(PersonalAxisVersion, axis.current_version_id)
                number = current.number + 1
            else:
                axis = PersonalAxis(
                    id=uuid4(),
                    user_id=owner,
                    current_version_id=uuid4(),
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(axis)
                await session.flush()
                number = 1
            version = PersonalAxisVersion(
                id=uuid4(),
                axis_id=axis.id,
                number=number,
                title=request.title,
                purpose=request.purpose,
                specification=specification.model_dump(mode="json"),
                specification_hash=specification.fingerprint,
                accepted_preview_id=preview_id,
                revision_hash=request.fingerprint,
                created_at=now,
            )
            session.add(version)
            await session.flush()
            axis.current_version_id, axis.updated_at = version.id, now
        return axis_response(axis, version)
