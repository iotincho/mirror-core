"""Pure snapshot policy for enabled, owner-scoped accepted axis versions."""

from copy import deepcopy

from src.core.extractors.personal_axes.models import AxisSpecification


def with_axes(baseline, definitions):
    config = deepcopy(baseline)
    if not definitions:
        return config
    specs = config.setdefault("extractors", [])
    for spec in specs:
        spec["key"] = spec["name"]
    for axis in definitions:
        specification = AxisSpecification.model_validate(axis.version.specification)
        if specification.fingerprint != axis.version.specification_hash:
            raise ValueError("axis_specification_mismatch")
        specs.append(
            {
                "name": "personal_axis",
                "key": f"axis:{axis.id}",
                "axis_id": str(axis.id),
                "version_id": str(axis.version.id),
                "specification": specification.model_dump(mode="json"),
            }
        )
    config["document_workflow_version"] = 5
    return config
