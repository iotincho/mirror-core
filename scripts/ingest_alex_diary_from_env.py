#!/usr/bin/env python3
"""Load Alex diary fixtures using an explicit authenticated session cookie."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.error import HTTPError

from ingest_alex_diary import format_http_error, load_fixtures, request_json

API_URL = os.environ.get("API_URL", "http://localhost:8080/api").rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--cookie", required=True, help="Authenticated el_espejo_session cookie")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    loaded = 0
    skipped = 0
    for path, payload in load_fixtures(Path("data/fixtures/alex-diary"), "baseline"):
        note_number = payload["metadata"]["note_number"]
        try:
            status, _, _ = request_json(f"{api_url}/documents", payload, args.cookie)
        except HTTPError as error:
            if error.code != 409:
                print(f"FAILED {note_number}: {format_http_error(error)}", file=sys.stderr)
                return 1
            print(f"SKIPPED {note_number}: already exists", flush=True)
            skipped += 1
            continue

        print(f"LOADED {note_number}: HTTP {status}", flush=True)
        loaded += 1

    print(f"Completed: {loaded} loaded, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
