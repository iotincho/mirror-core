"""Serialize detached definitions using the existing public wire format."""


def axis_response(axis):
    return {
        "id": str(axis.id),
        "enabled": axis.enabled,
        "current_version_id": str(axis.current_version_id),
        "version": {
            "id": str(axis.version.id),
            "number": axis.version.number,
            "title": axis.version.title,
            "purpose": axis.version.purpose,
            "specification": axis.version.specification,
            "specification_hash": axis.version.specification_hash,
            "created_at": axis.version.created_at.isoformat(),
        },
    }
