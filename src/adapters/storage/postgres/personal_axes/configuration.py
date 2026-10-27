"""Read enabled versions and account grant inside the caller's acceptance transaction."""

from sqlalchemy import select

from src.adapters.storage.postgres.personal_axes.definitions import definition
from src.adapters.storage.postgres.personal_axes.laboratory import PostgresLaboratory
from src.adapters.storage.postgres.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.core.extractors.personal_axes.configuration import with_axes


async def user_workflow_config(session, owner, baseline, *, enabled):
    state = await PostgresLaboratory(session=session).read(owner) if enabled else None
    if state is None or not state.active or not state.granted:
        return with_axes(baseline, ())
    versions = (
        await session.execute(
            select(PersonalAxis, PersonalAxisVersion)
            .join(PersonalAxisVersion, PersonalAxis.current_version_id == PersonalAxisVersion.id)
            .where(PersonalAxis.user_id == owner, PersonalAxis.enabled.is_(True))
            .order_by(PersonalAxis.id)
        )
    ).all()
    return with_axes(baseline, [definition(*pair) for pair in versions])
