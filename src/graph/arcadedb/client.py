"""Small HTTP client for ArcadeDB commands, queries, and transactions."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import httpx

from src.config import get_settings


class ArcadeDBClientError(RuntimeError):
    """Raised when ArcadeDB rejects a request or cannot be reached."""


class ArcadeDBTransaction:
    def __init__(self, client: ArcadeDBHTTPClient, session_id: str) -> None:
        self._client = client
        self._session_id = session_id

    def command(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]:
        return self._client.command(
            statement,
            params,
            language=language,
            session_id=self._session_id,
        )

    def query(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]:
        return self._client.query(
            statement,
            params,
            language=language,
            session_id=self._session_id,
        )


class ArcadeDBHTTPClient:
    """Dependency-free client for the stable ArcadeDB HTTP API."""

    def __init__(self, http_url: str, database: str, username: str, password: str) -> None:
        self._base_url = http_url.rstrip("/")
        self._database = quote(database, safe="")
        credentials = f"{username}:{password}".encode()
        self._authorization = f"Basic {base64.b64encode(credentials).decode()}"

    def command(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self._execute("command", statement, params, language, session_id)

    def query(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self._execute("query", statement, params, language, session_id)

    @contextmanager
    def transaction(self) -> Iterator[ArcadeDBTransaction]:
        session_id = self._control("begin", return_session=True)
        assert session_id is not None
        transaction = ArcadeDBTransaction(self, session_id)
        try:
            yield transaction
            self._control("commit", session_id=session_id)
        except BaseException:
            try:
                self._control("rollback", session_id=session_id)
            except ArcadeDBClientError:
                pass
            raise

    def close(self) -> None:
        """The stateless HTTP transport holds no persistent resources."""

    def _execute(
        self,
        operation: str,
        statement: str,
        params: dict[str, Any] | None,
        language: str,
        session_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"language": language, "command": statement}
        if params:
            payload["params"] = params
        response, _ = self._request(operation, payload=payload, session_id=session_id)
        return response

    def _control(
        self,
        operation: str,
        *,
        session_id: str | None = None,
        return_session: bool = False,
    ) -> str | None:
        _, headers = self._request(operation, session_id=session_id)
        if not return_session:
            return None
        value = headers.get("arcadedb-session-id")
        if not value:
            raise ArcadeDBClientError("ArcadeDB did not return a transaction session id")
        return value

    def _request(
        self,
        operation: str,
        *,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], Any]:
        headers = {"Authorization": self._authorization}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        if session_id:
            headers["arcadedb-session-id"] = session_id
        request = Request(
            f"{self._base_url}/api/v1/{operation}/{self._database}",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                parsed = json.loads(body) if body else {}
                return parsed, response.headers
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise ArcadeDBClientError(
                f"ArcadeDB rejected {operation} with HTTP {error.code}: {detail}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise ArcadeDBClientError(f"ArcadeDB is unavailable during {operation}") from error


class AsyncArcadeDBTransaction:
    """Session identity belongs to this transaction, never to the shared transport."""

    def __init__(self, client: AsyncArcadeDBHTTPClient, session_id: str) -> None:
        self._client = client
        self._session_id = session_id

    async def command(
        self, statement: str, params: dict[str, Any] | None = None, *, language: str = "sql",
    ) -> dict[str, Any]:
        return await self._client.command(
            statement, params, language=language, session_id=self._session_id
        )

    async def query(
        self, statement: str, params: dict[str, Any] | None = None, *, language: str = "sql",
    ) -> dict[str, Any]:
        return await self._client.query(
            statement, params, language=language, session_id=self._session_id
        )


class AsyncArcadeDBHTTPClient:
    """Async runtime transport; the sync client remains for schema/admin commands."""

    def __init__(
        self,
        http_url: str,
        database: str,
        username: str,
        password: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = http_url.rstrip("/")
        self._database = quote(database, safe="")
        credentials = f"{username}:{password}".encode()
        self._authorization = f"Basic {base64.b64encode(credentials).decode()}"
        self._http = client
        self._owns_client = client is None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            settings = get_settings()
            self._http = httpx.AsyncClient(
                timeout=settings.graph_timeout_seconds,
                limits=httpx.Limits(max_connections=settings.graph_max_connections),
            )
        return self._http

    async def command(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._execute("command", statement, params, language, session_id)

    async def query(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._execute("query", statement, params, language, session_id)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncArcadeDBTransaction]:
        session_id = await self._control("begin", return_session=True)
        assert session_id is not None
        try:
            yield AsyncArcadeDBTransaction(self, session_id)
            await self._control("commit", session_id=session_id)
        except BaseException:
            try:
                await asyncio.shield(self._control("rollback", session_id=session_id))
            except ArcadeDBClientError:
                pass
            raise

    async def close(self) -> None:
        if self._owns_client and self._http is not None:
            try:
                await self._http.aclose()
            finally:
                self._http = None

    async def _execute(
        self,
        operation: str,
        statement: str,
        params: dict[str, Any] | None,
        language: str,
        session_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"language": language, "command": statement}
        if params:
            payload["params"] = params
        response, _ = await self._request(operation, payload=payload, session_id=session_id)
        return response

    async def _control(
        self,
        operation: str,
        *,
        session_id: str | None = None,
        return_session: bool = False,
    ) -> str | None:
        _, headers = await self._request(operation, session_id=session_id)
        if not return_session:
            return None
        value = headers.get("arcadedb-session-id")
        if not value:
            raise ArcadeDBClientError("ArcadeDB did not return a transaction session id")
        return value

    async def _request(
        self,
        operation: str,
        *,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], httpx.Headers]:
        headers = {"Authorization": self._authorization}
        if session_id:
            headers["arcadedb-session-id"] = session_id
        try:
            response = await self._get_http().post(
                f"{self._base_url}/api/v1/{operation}/{self._database}",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return (response.json() if response.content else {}), response.headers
        except httpx.HTTPStatusError as error:
            raise ArcadeDBClientError(
                f"ArcadeDB rejected {operation} with HTTP {error.response.status_code}"
            ) from error
        except httpx.RequestError as error:
            raise ArcadeDBClientError(f"ArcadeDB is unavailable during {operation}") from error
