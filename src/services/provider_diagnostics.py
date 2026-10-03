"""Provider error metadata without logging request bodies or credentials."""

from typing import Any


def provider_error_details(error: Exception) -> dict[str, Any]:
    """Read SDK metadata without depending on a particular SDK exception type."""
    return {
        "error_type": type(error).__name__,
        "upstream_status": getattr(error, "status_code", None),
        "upstream_request_id": getattr(error, "request_id", None),
        "error_code": getattr(error, "code", None),
        "error_param": getattr(error, "param", None),
    }
