"""HTTP translation for safe semantic axis errors."""

from src.core.extractors.personal_axes.previews import SampleSourceUnavailable

STATUSES = {
    "axis_access_disabled": 404,
    "axis_catalogue_limit": 422,
    "axis_cursor_invalid": 422,
    "axis_evidence_invalid": 503,
    "axis_finding_not_found": 404,
    "axis_graph_incomplete": 503,
    "axis_graph_limit": 422,
    "axis_graph_unavailable": 503,
    "axis_history_not_found": 404,
    "axis_input_too_long": 422,
    "axis_node_invalid": 422,
    "axis_node_not_found": 404,
    "axis_not_found": 404,
    "axis_preview_already_accepted": 410,
    "axis_preview_expired": 410,
    "axis_preview_limit": 429,
    "axis_preview_not_found": 404,
    "axis_provider_configuration": 503,
    "axis_source_unavailable": 409,
    "axis_specification_mismatch": 503,
    "axis_storage_unavailable": 503,
    "axis_version_not_found": 404,
}


def axis_status(error):
    if isinstance(error, SampleSourceUnavailable):
        return 404
    return STATUSES.get(error if isinstance(error, str) else error.code, 409)
