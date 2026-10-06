#!/usr/bin/env python3
"""Load the synthetic Alex diary fixtures through El Espejo's HTTP API.

The script is intentionally sequential: a failure stops the run so a partial
corpus cannot go unnoticed. Fixture UUIDs are stable, so API 409 responses can
optionally be treated as already-loaded documents with ``--skip-existing``.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.client import HTTPMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIRECTORY = REPOSITORY_ROOT / "data" / "fixtures" / "alex-diary"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load Alex diary fixtures through POST /documents."
    )
    parser.add_argument("--api-url", default="http://localhost:8000", help="El Espejo API base URL")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIRECTORY,
        help="Directory containing one JSON fixture per note",
    )
    parser.add_argument(
        "--phase",
        choices=("baseline", "incremental", "all"),
        default="baseline",
        help="Fixtures to load (default: baseline, notes 01–15)",
    )
    parser.add_argument(
        "--cookie",
        help="Authenticated Cookie header value, for example 'el_espejo_session=...'.",
    )
    parser.add_argument(
        "--username", help="Username used to obtain a session from POST /auth/login"
    )
    parser.add_argument(
        "--password", help="Password used to obtain a session from POST /auth/login"
    )
    parser.add_argument(
        "--skip-existing", action="store_true", help="Continue when a fixture returns HTTP 409"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and list fixtures without HTTP requests"
    )
    return parser.parse_args()


def load_fixtures(directory: Path, phase: str) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.is_dir():
        raise ValueError(f"Fixtures directory does not exist: {directory}")

    fixtures: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {path}: {error}") from error

        if not isinstance(payload, dict):
            raise ValueError(f"Fixture must be a JSON object: {path}")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"Fixture metadata must be an object: {path}")
        if phase != "all" and metadata.get("phase") != phase:
            continue
        fixtures.append((path, payload))

    if not fixtures:
        raise ValueError(f"No {phase!r} fixtures found in {directory}")
    return fixtures


def request_json(
    url: str,
    payload: dict[str, Any],
    cookie: str | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any, HTTPMessage]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **(extra_headers or {}),
    }
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- operator supplies the destination.
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else None, response.headers


def login(api_url: str, username: str, password: str) -> str:
    _, _, headers = request_json(
        f"{api_url}/auth/login", {"username": username, "password": password}
    )
    set_cookie = headers.get("Set-Cookie")
    if not set_cookie:
        raise RuntimeError("Login succeeded but did not return a session cookie")
    return set_cookie.split(";", maxsplit=1)[0]


def main() -> int:
    args = parse_args()
    if bool(args.username) != bool(args.password):
        print("--username and --password must be provided together", file=sys.stderr)
        return 2
    if args.cookie and args.username:
        print("Use either --cookie or --username/--password, not both", file=sys.stderr)
        return 2

    try:
        fixtures = load_fixtures(args.fixtures_dir, args.phase)
    except ValueError as error:
        print(f"Fixture error: {error}", file=sys.stderr)
        return 2

    if args.dry_run:
        for path, payload in fixtures:
            print(f"WOULD LOAD {payload['metadata']['note_number']}: {path.name}")
        return 0

    api_url = args.api_url.rstrip("/")
    cookie = args.cookie
    try:
        if args.username:
            cookie = login(api_url, args.username, args.password)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"Authentication failed: {format_http_error(error)}", file=sys.stderr)
        return 1

    loaded = 0
    skipped = 0
    for path, payload in fixtures:
        note_number = payload["metadata"].get("note_number", path.name)
        try:
            status, _, _ = request_json(f"{api_url}/documents", payload, cookie)
        except HTTPError as error:
            if error.code == 409 and args.skip_existing:
                print(f"SKIPPED {note_number}: already exists")
                skipped += 1
                continue
            print(f"FAILED {note_number}: {format_http_error(error)}", file=sys.stderr)
            return 1
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"FAILED {note_number}: {format_http_error(error)}", file=sys.stderr)
            return 1

        print(f"LOADED {note_number}: HTTP {status}")
        loaded += 1

    print(f"Completed: {loaded} loaded, {skipped} skipped.")
    return 0


def format_http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = error.read().decode("utf-8")
        except UnicodeDecodeError:
            detail = "<non-UTF-8 response body>"
        return f"HTTP {error.code}: {detail}"
    return str(error)


if __name__ == "__main__":
    raise SystemExit(main())
