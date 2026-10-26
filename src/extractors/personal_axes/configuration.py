"""Snapshot the owner's approved definitions inside the accepting SQL transaction."""

from copy import deepcopy

from sqlalchemy import select

from src.core.extractors.personal_axes.models import AxisSpecification
from src.extractors.personal_axes.access import laboratory_available
from src.extractors.personal_axes.models import PersonalAxis, PersonalAxisVersion


async def user_workflow_config(session, owner, baseline):
    config = deepcopy(baseline)
    if not await laboratory_available(session, owner):
        return config
    versions = (
        await session.execute(
            select(PersonalAxis, PersonalAxisVersion)
            .join(PersonalAxisVersion, PersonalAxis.current_version_id == PersonalAxisVersion.id)
            .where(PersonalAxis.user_id == owner, PersonalAxis.enabled.is_(True))
            .order_by(PersonalAxis.id)
        )
    ).all()
    if not versions:
        return config
    specs = config.setdefault("extractors", [])
    for spec in specs:
        spec["key"] = spec["name"]
    for axis, version in versions:
        specification = AxisSpecification.model_validate(version.specification)
        if specification.fingerprint != version.specification_hash:
            raise ValueError("axis_specification_mismatch")
        specs.append(
            {
                "name": "personal_axis",
                "key": f"axis:{axis.id}",
                "axis_id": str(axis.id),
                "version_id": str(version.id),
                "specification": specification.model_dump(mode="json"),
            }
        )
    config["document_workflow_version"] = 5
    return config
