import logging
import traceback

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def error_app() -> FastAPI:
    test_app = FastAPI(exception_handlers=app.exception_handlers.copy())

    @test_app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("unexpected backend failure")

    @test_app.get("/http/{code}")
    async def http_error(code: int):
        try:
            raise ValueError("original provider failure")
        except ValueError as error:
            raise HTTPException(
                status_code=code, detail="Service unavailable", headers={"Retry-After": "5"}
            ) from error

    @test_app.get("/workspace")
    async def workspace_error():
        raise StarletteHTTPException(status_code=503, detail="Personal workspace is preparing")

    return test_app


@pytest.mark.anyio
@pytest.mark.parametrize("code", [500, 502, 503, 504, 509])
async def test_http_server_errors_log_chained_traceback(error_app, caplog, code):
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=error_app), base_url="http://test"
        ) as client:
            response = await client.get(f"/http/{code}?token=private")

    assert response.status_code == code
    assert response.json() == {"detail": "Service unavailable"}
    assert response.headers["Retry-After"] == "5"
    record, = caplog.records
    assert record.exc_info is not None
    assert "ValueError: original provider failure" in caplog.text
    assert f"method=GET path=/http/{code} status_code={code}" in caplog.text
    assert "token=private" not in caplog.text


@pytest.mark.anyio
async def test_unexpected_error_logs_traceback_and_returns_generic_500(error_app, caplog):
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=error_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/unexpected")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    record, = caplog.records
    assert "RuntimeError: unexpected backend failure" in caplog.text
    assert "in unexpected" in "".join(traceback.format_exception(*record.exc_info))


@pytest.mark.anyio
async def test_503_without_cause_logs_raise_location(error_app, caplog):
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=error_app), base_url="http://test"
        ) as client:
            response = await client.get("/workspace")

    assert response.status_code == 503
    assert "in workspace_error" in caplog.text
    assert "Personal workspace is preparing" in caplog.text


@pytest.mark.anyio
async def test_client_errors_are_not_logged_as_server_errors(error_app, caplog):
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=error_app), base_url="http://test"
        ) as client:
            response = await client.get("/http/409")

    assert response.status_code == 409
    assert not caplog.records
