#!/usr/bin/env python3
"""Request durable persistence of an original document without re-uploading or extracting."""

import argparse
import os
import sys
from urllib.error import HTTPError, URLError
from uuid import UUID, uuid4

from ingest_alex_diary import format_http_error, request_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_id", type=UUID)
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8080/api"))
    parser.add_argument("--cookie", required=True, help="Authenticated el_espejo_session cookie")
    parser.add_argument(
        "--key", type=UUID, default=None, help="Reuse this key when retrying a lost response"
    )
    args = parser.parse_args()
    key = args.key or uuid4()
    print(f"Idempotency-Key: {key}")
    try:
        status, body, _ = request_json(
            f"{args.api_url.rstrip('/')}/v2/documents/{args.document_id}/processing",
            {},
            args.cookie,
            extra_headers={"Idempotency-Key": str(key)},
        )
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Reprocessing failed: {format_http_error(error)}", file=sys.stderr)
        return 1
    print(f"ACCEPTED {args.document_id}: HTTP {status}; processing={body['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
