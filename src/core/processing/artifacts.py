"""The stable processing artifact hash; preserve its historical JSON encoding."""

import hashlib
import json


def artifact_digest(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
