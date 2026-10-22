"""Opaque, context-bound keyset cursors shared by preview and active branches."""

import base64
import json

from src.extractors.contracts import digest
from src.extractors.personal_axes.contracts import AxisError


def encode(value):
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True).decode()


def position(cursor, scope):
    if cursor is None:
        return ""
    try:
        if len(cursor) > 4096:
            raise ValueError()
        data = json.loads(decode(cursor))
        if data["scope"] != digest(scope) or not isinstance(data["after"], str):
            raise ValueError()
        return data["after"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise AxisError("axis_cursor_invalid", 422) from None


def next_cursor(after, scope):
    return encode(json.dumps({"scope": digest(scope), "after": after}))


def page(items, scope, cursor, limit, key):
    after = position(cursor, scope)
    selected = [item for item in sorted(items, key=key) if key(item) > after][: limit + 1]
    more = len(selected) > limit
    selected = selected[:limit]
    return selected, next_cursor(key(selected[-1]), scope) if more else None
