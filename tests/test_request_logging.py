import logging

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from src.adapters.access.api.public.request_logging import RequestLoggingMiddleware
from src.bootstrap.public_api import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Payload(BaseModel):
    count: int


@pytest.fixture
def observed_app():
    test_app = FastAPI(exception_handlers=app.exception_handlers.copy())
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.post("/upload")
    async def upload(request: Request):
        await request.body()
        return JSONResponse({"accepted": True}, status_code=202)

    @test_app.post("/validate")
    async def validate(payload: Payload):
        return {"count": payload.count}

    @test_app.post("/reject/{code}")
    async def reject(code: int):
        raise HTTPException(code, "private rejection detail")

    @test_app.get("/direct/{code}")
    async def direct(code: int):
        return JSONResponse({"detail": "Request failed"}, status_code=code)

    @test_app.post("/unexpected")
    async def unexpected():
        raise RuntimeError("unexpected failure")

    return test_app


@pytest.mark.anyio
@pytest.mark.parametrize("code", [401, 403, 409, 413, 415, 422, 429, 503])
async def test_rejected_requests_have_correlated_logs(observed_app, caplog, code):
    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/reject/{code}?token=private-query", content="private audio bytes",
                headers={"Cookie": "session=private-cookie", "Authorization": "private-auth"},
            )
    assert response.status_code == code
    request_id = response.headers["X-Request-ID"]
    assert f"request_id={request_id}" in caplog.text
    assert f"status_code={code}" in caplog.text
    # Existing 5xx tracebacks remain available; new rejection logs contain no payload/detail.
    summary = "\n".join(
        r.getMessage() for r in caplog.records
        if r.name == "src.adapters.access.api.public.request_logging"
    )
    for secret in ["private-query", "private-cookie", "private-auth", "private audio bytes",
                   "private rejection detail"]:
        assert secret not in summary


@pytest.mark.anyio
async def test_validation_logs_only_error_types(observed_app, caplog):
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            response = await client.post("/validate", json={"count": "private note content"})
    assert response.status_code == 422
    assert "RequestValidationError" in caplog.text
    assert "int_parsing" in caplog.text
    assert "private note content" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("code", [401, 500])
async def test_direct_error_response_is_also_logged(observed_app, caplog, code):
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            response = await client.get(f"/direct/{code}")
    assert response.status_code == code
    assert f"method=GET path=/direct/{code}" in caplog.text
    assert f"status_code={code}" in caplog.text


@pytest.mark.anyio
async def test_unhandled_failure_keeps_request_id_and_traceback(observed_app, caplog):
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post("/unexpected")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert f"request_id={response.headers['X-Request-ID']}" in caplog.text
    assert "RuntimeError: unexpected failure" in caplog.text


@pytest.mark.anyio
async def test_upload_disconnect_is_logged_without_a_server_crash(observed_app, caplog):
    messages = iter([
        {"type": "http.request", "body": b"private audio", "more_body": True},
        {"type": "http.disconnect"},
    ])
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.INFO):
        await observed_app(
            {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/upload", "raw_path": b"/upload",
             "query_string": b"token=private-query", "root_path": "", "headers": []},
            receive, send,
        )
    assert sent[0]["status"] == 499
    assert "http_client_disconnected" in caplog.text
    assert "received_bytes=13" in caplog.text
    assert "http_server_error" not in caplog.text
    assert "private audio" not in caplog.text
    assert "private-query" not in caplog.text


@pytest.mark.anyio
async def test_successful_upload_has_start_and_acceptance(observed_app, caplog):
    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            response = await client.post("/upload", content=b"audio")
    assert response.status_code == 202
    assert "http_write_started" in caplog.text
    assert "status_code=202 received_bytes=5" in caplog.text
    assert caplog.text.count(f"request_id={response.headers['X-Request-ID']}") == 2
