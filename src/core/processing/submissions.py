"""Stable request fingerprints and safe conflicts shared by acceptance ports."""

import hashlib
import json


class SubmissionConflict(ValueError):
    pass


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
