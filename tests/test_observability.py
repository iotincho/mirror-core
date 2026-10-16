import json
from types import SimpleNamespace

import httpx
import pytest
import sentry_sdk
from fastapi import FastAPI, HTTPException
from sentry_sdk.transport import Transport

from src import observability
from src.api.request_logging import RequestLoggingMiddleware
from src.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def captured(monkeypatch):
    class Events(list):
        transactions = None

    events = Events()
    events.transactions = []

    class MemoryTransport(Transport):
        def capture_envelope(self, envelope):
            for item in envelope.items:
                if item.headers.get("type") == "event":
                    events.append(item.payload.json)
                elif item.headers.get("type") == "transaction":
                    events.transactions.append(item.payload.json)

    previous = sentry_sdk.get_global_scope().client
    actual_init = sentry_sdk.init
    settings = SimpleNamespace(
        sentry_dsn="https://public@example.invalid/1", sentry_release="test-release",
        environment="test",
        sentry_traces_sample_rate=1.0,
    )
    monkeypatch.setattr(observability, "get_settings", lambda: settings)
    monkeypatch.setattr(
        sentry_sdk, "init", lambda **kw: actual_init(**kw, transport=MemoryTransport)
    )
    observability.initialize_sentry("api")
    yield events
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(previous)


def test_disabled_sentry_does_not_initialize_or_capture(monkeypatch):
    monkeypatch.setattr(observability, "get_settings", lambda: SimpleNamespace(sentry_dsn=""))
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: pytest.fail("Sentry initialized"))
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda *a: pytest.fail("Sentry captured"))
    observability.initialize_sentry("api")
    observability.report_issue("upload_failed", ValueError("private"))


def test_sdk_transport_receives_only_safe_exception_context(captured):
    with sentry_sdk.isolation_scope() as scope:
        scope.set_user({"email": "secret@example.invalid", "ip_address": "192.0.2.1"})
        scope.set_context("note", {"text": "private note"})
        scope.set_extra("audio", "private audio")
        try:
            raise ValueError("private provider response")
        except ValueError as error:
            observability.report_issue("workflow_failure", error, processing_id="job-1",
                                       error_code="invalid_audio", retry=False)
    assert len(captured) == 1
    event = captured[0]
    assert event["release"] == "test-release"
    assert event["environment"] == "test"
    assert event["tags"]["processing_id"] == "job-1"
    assert event["tags"]["error_code"] == "invalid_audio"
    assert event["exception"]["values"][0]["stacktrace"]["frames"]
    serialized = json.dumps(event)
    for secret in ["private provider response", "private note", "private audio",
                   "secret@example.invalid", "192.0.2.1"]:
        assert secret not in serialized


@pytest.mark.anyio
async def test_rejected_upload_is_correlated_without_request_payload(captured):
    test_app = FastAPI(exception_handlers=app.exception_handlers.copy())
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.post("/upload")
    async def upload():
        raise HTTPException(415, "private filename")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post("/upload?secret=private-query", content="private audio")
    assert response.status_code == 415
    assert len(captured) == 1
    assert captured[0]["tags"]["request_id"] == response.headers["X-Request-ID"]
    assert captured[0]["tags"]["status_code"] == "415"
    assert "private" not in json.dumps(captured)


def test_scrubber_removes_nested_sensitive_data_and_attachments():
    hint = {"attachments": [b"private audio"]}
    event = observability.scrub_event({
        "request": {"data": "private note", "headers": {"Cookie": "private cookie"}},
        "message": "private message", "breadcrumbs": [{"message": "private log"}],
        "exception": {"values": [{"type": "Error", "value": "private exception",
            "mechanism": {"type": "test", "data": {"sql": "private SQL"}},
            "stacktrace": {"frames": [{"filename": "app.py", "lineno": 12,
                "vars": {"note": "private note"}, "pre_context": ["private code"]}]}}]},
    }, hint)
    assert "private" not in json.dumps(event)
    assert "attachments" not in hint


@pytest.mark.anyio
async def test_unexpected_api_error_is_captured_once_with_request_id(captured):
    test_app = FastAPI(exception_handlers=app.exception_handlers.copy())
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.post("/upload")
    async def upload():
        raise RuntimeError("private provider payload")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/upload")
    assert response.status_code == 500
    assert len(captured) == 1
    assert captured[0]["tags"]["request_id"] == response.headers["X-Request-ID"]
    assert "private provider payload" not in json.dumps(captured)


def test_transaction_and_error_keep_trace_identity_without_private_data(captured):
    with sentry_sdk.start_transaction(name="src.test.operation", op="app.operation") as transaction:
        with sentry_sdk.start_span(op="http.client", name="GET /private?token=private"):
            try:
                raise ValueError("private note")
            except ValueError as error:
                observability.report_issue("workflow_failure", error)
    assert len(captured.transactions) == 1
    trace = captured.transactions[0]
    assert trace["contexts"]["trace"]["trace_id"] == transaction.trace_id
    assert captured[0]["contexts"]["trace"]["trace_id"] == transaction.trace_id
    assert trace["transaction"] == "src.test.operation"
    assert trace["spans"][0]["description"] == "http.client"
    assert "private" not in json.dumps(trace)


@pytest.mark.anyio
async def test_api_continues_the_incoming_browser_trace(captured):
    test_app = FastAPI(exception_handlers=app.exception_handlers.copy())
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.post("/upload")
    async def upload():
        raise HTTPException(415, "private note")

    incoming_trace = "a" * 32
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        await client.post("/upload", headers={"sentry-trace": f"{incoming_trace}-{'b' * 16}-1"})
    assert captured.transactions[0]["contexts"]["trace"]["trace_id"] == incoming_trace
    assert captured[0]["contexts"]["trace"]["trace_id"] == incoming_trace


def test_worker_operation_has_its_own_trace_and_processing_id(captured):
    with observability.trace_operation("processing.execute", processing_id="job-1"):
        observability.report_issue("workflow_failure", ValueError("private note"))
    trace = captured.transactions[0]
    assert trace["transaction"] == "processing.execute"
    assert trace["tags"]["processing_id"] == "job-1"
    assert trace["contexts"]["trace"]["trace_id"] == captured[0]["contexts"]["trace"]["trace_id"]
    assert "private" not in json.dumps(trace)
