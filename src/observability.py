"""Opt-in error reporting with an allowlist of technical diagnostic fields."""

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from src.config import get_settings

SAFE_TAGS = {
    "service", "operation", "request_id", "status_code", "method", "route",
    "processing_id", "resource_id", "workflow", "stage", "attempt", "error_code", "retry",
}


def scrub_event(event, hint):
    """Exception messages, SQL, locals and request data can contain private material."""
    hint.pop("attachments", None)
    clean = {key: event[key] for key in (
        "event_id", "timestamp", "platform", "level", "release", "environment", "sdk",
        "fingerprint", "logger",
    ) if key in event}
    clean["tags"] = {key: value for key, value in event.get("tags", {}).items() if key in SAFE_TAGS}
    values = []
    for value in event.get("exception", {}).get("values", []):
        safe = {key: value[key] for key in ("type", "module") if key in value}
        if "mechanism" in value:
            safe["mechanism"] = {
                key: value["mechanism"][key] for key in ("type", "handled")
                if key in value["mechanism"]
            }
        safe["value"] = "Exception message redacted"
        frames = value.get("stacktrace", {}).get("frames", [])
        safe["stacktrace"] = {"frames": [
            {key: frame[key] for key in ("filename", "function", "module", "lineno", "in_app")
             if key in frame} for frame in frames
        ]}
        values.append(safe)
    if values:
        clean["exception"] = {"values": values}
    else:
        clean["message"] = clean["tags"].get("operation", "backend_error")
    return clean


def initialize_sentry(service: str) -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.sentry_release or None,
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[
            AtexitIntegration(), ExcepthookIntegration(), DedupeIntegration(),
            StarletteIntegration(), FastApiIntegration(),
        ],
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        traces_sample_rate=0,
        profiles_sample_rate=0,
        auto_session_tracking=False,
        before_send=scrub_event,
    )
    sentry_sdk.set_tag("service", service)


def report_issue(operation: str, error: Exception | None = None, **tags) -> None:
    if not get_settings().sentry_dsn:
        return
    # Diagnostics must never change upload, retry or durable-processing behavior.
    try:
        with sentry_sdk.isolation_scope() as scope:
            scope.set_tag("operation", operation)
            for key, value in tags.items():
                if key in SAFE_TAGS and value is not None:
                    scope.set_tag(key, str(value))
            scope.fingerprint = ["{{ default }}", operation, str(tags.get("error_code", ""))]
            if error is not None:
                sentry_sdk.capture_exception(error)
            else:
                sentry_sdk.capture_message(operation, level="warning")
    except Exception:
        pass  # The original failure remains in local logs; Sentry is best effort.
