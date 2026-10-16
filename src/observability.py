"""Opt-in error reporting with an allowlist of technical diagnostic fields."""

from contextlib import contextmanager

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

TRACE_FIELDS = {"trace_id", "span_id", "parent_span_id", "op", "status", "origin"}


def scrub_trace(trace):
    return {key: value for key, value in trace.items() if key in TRACE_FIELDS}


def scrub_transaction(event, hint):
    clean = scrub_event(event, hint)
    clean.update({key: event[key] for key in (
        "type", "start_timestamp", "timestamp",
    ) if key in event})
    # Endpoint/function names are selected by our integrations, never raw URLs or payloads.
    name = event.get("transaction", "")
    clean["transaction"] = (
        name if name.startswith("src.") and name.replace(".", "").replace("_", "").isalnum()
        else name if name in {"processing.execute", "processing.dispatch"} else "backend.request"
    )
    clean["transaction_info"] = {"source": "component"}
    clean["spans"] = [{
        **scrub_trace(span),
        **{key: span[key] for key in ("start_timestamp", "timestamp") if key in span},
        "description": span.get("op", "operation"),
    } for span in event.get("spans", [])]
    return clean


def scrub_event(event, hint):
    """Exception messages, SQL, locals and request data can contain private material."""
    hint.pop("attachments", None)
    clean = {key: event[key] for key in (
        "event_id", "timestamp", "platform", "level", "release", "environment", "sdk",
        "fingerprint", "logger",
    ) if key in event}
    clean["tags"] = {key: value for key, value in event.get("tags", {}).items() if key in SAFE_TAGS}
    trace = event.get("contexts", {}).get("trace")
    if trace:
        clean["contexts"] = {"trace": scrub_trace(trace)}
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
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        trace_lifecycle="static",
        profiles_sample_rate=0,
        auto_session_tracking=False,
        before_send=scrub_event,
        before_send_transaction=scrub_transaction,
        trace_propagation_targets=[],
    )
    sentry_sdk.set_tag("service", service)


@contextmanager
def trace_operation(operation: str, **tags):
    if not get_settings().sentry_dsn:
        yield
        return
    with sentry_sdk.isolation_scope() as scope:
        for key, value in tags.items():
            if key in SAFE_TAGS:
                scope.set_tag(key, str(value))
        with sentry_sdk.start_transaction(name=operation, op="queue.process"):
            yield


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
