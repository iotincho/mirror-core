#!/usr/bin/env python3
"""Resumable baseline loader using an explicit authenticated session cookie."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ingest_alex_diary import load_fixtures

API_URL = os.environ.get("API_URL", "http://localhost:8080/api").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 180


def post(path: str, payload: dict, cookie: str | None = None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(f"{API_URL}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
    return urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cookie", required=True, help="Authenticated el_espejo_session cookie")
    args = parser.parse_args()

    for _, payload in load_fixtures(Path("data/fixtures/alex-diary"), "baseline"):
        note = payload["metadata"]["note_number"]
        try:
            with post("/documents", payload, args.cookie) as response:
                print(f"LOADED {note}: HTTP {response.status}", flush=True)
        except HTTPError as error:
            if error.code == 409:
                print(f"SKIPPED {note}: already exists", flush=True)
                continue
            print(f"FAILED {note}: HTTP {error.code}: {error.read().decode()}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
