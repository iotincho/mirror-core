"""Administrative ArcadeDB adapter used only while provisioning workspaces."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from src.graph.arcadedb.client import ArcadeDBClientError, ArcadeDBHTTPClient

RUNTIME_GROUP = "el_espejo_runtime"
_CRUD_ACCESS = ["createRecord", "readRecord", "updateRecord", "deleteRecord"]


class ArcadeDBAdminError(ArcadeDBClientError):
    """A safe administrative failure that never includes credentials."""


class ArcadeDBAdminClient:
    """Minimal client for the root-only ArcadeDB server endpoints."""

    def __init__(self, http_url: str, username: str, password: str) -> None:
        self._base_url = http_url.rstrip("/")
        credentials = f"{username}:{password}".encode()
        self._authorization = f"Basic {base64.b64encode(credentials).decode()}"

    def database_exists(self, database_name: str) -> bool:
        response = self._request(f"/api/v1/exists/{quote(database_name, safe='')}")
        return bool(response.get("result"))

    def ensure_database(self, database_name: str) -> None:
        if self.database_exists(database_name):
            return
        try:
            self._request(
                "/api/v1/server",
                method="POST",
                payload={"command": f"create database {database_name}"},
            )
        except ArcadeDBAdminError:
            if not self.database_exists(database_name):
                raise

    def ensure_runtime_principal(
        self,
        *,
        database_name: str,
        username: str,
        password: str,
    ) -> None:
        self._request(
            "/api/v1/server/groups",
            method="POST",
            payload={
                "database": database_name,
                "name": RUNTIME_GROUP,
                "access": [],
                "types": {"*": {"access": _CRUD_ACCESS}},
                "resultSetLimit": -1,
                "readTimeout": -1,
            },
        )
        users = self._request("/api/v1/server/users").get("result", [])
        payload = {
            "name": username,
            "password": password,
            "databases": {database_name: [RUNTIME_GROUP]},
        }
        if any(isinstance(user, dict) and user.get("name") == username for user in users):
            self._request(
                f"/api/v1/server/users?{urlencode({'name': username})}",
                method="PUT",
                payload=payload,
            )
        else:
            self._request("/api/v1/server/users", method="POST", payload=payload)

    def verify_runtime_principal(
        self,
        *,
        database_name: str,
        username: str,
        password: str,
    ) -> None:
        runtime = ArcadeDBHTTPClient(self._base_url, database_name, username, password)
        runtime.query("SELECT 1 AS value")
        visible = self._request_as(
            username,
            password,
            "/api/v1/databases",
        ).get("result", [])
        if visible != [database_name]:
            raise ArcadeDBAdminError("runtime principal has an unexpected database scope")

    def _request_as(
        self,
        username: str,
        password: str,
        path: str,
    ) -> dict[str, Any]:
        credentials = f"{username}:{password}".encode()
        authorization = f"Basic {base64.b64encode(credentials).decode()}"
        return self._request(path, authorization=authorization)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": authorization or self._authorization}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        request = Request(f"{self._base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except HTTPError as error:
            raise ArcadeDBAdminError(
                f"ArcadeDB admin request failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise ArcadeDBAdminError("ArcadeDB admin endpoint is unavailable") from error
