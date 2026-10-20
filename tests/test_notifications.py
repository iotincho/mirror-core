import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.notifications.repository import decode_cursor, encode_cursor
from src.notifications.schemas import AnnouncementContent, NotificationAction, ReadAll


def test_publication_defaults_to_fifteen_days_and_actions_are_closed():
    content = AnnouncementContent(key="new-feature", title="New", summary="Summary", body="Details")
    assert content.lifetime_days == 15
    with pytest.raises(ValidationError):
        NotificationAction(type="open_url", url="https://example.com")
    with pytest.raises(ValidationError):
        NotificationAction(type="open_invitation")
    with pytest.raises(ValidationError):
        NotificationAction(type="open_capture", invitation_id=uuid4())
    with pytest.raises(ValidationError):
        ReadAll(through="2026-10-20T10:00:00")
    with pytest.raises(ValidationError):
        AnnouncementContent(
            key="private-invitation",
            title="New",
            summary="Summary",
            body="Details",
            action=NotificationAction(type="open_invitation", invitation_id=uuid4()),
        )


@pytest.mark.parametrize("read_at", [None, datetime.now(UTC)])
def test_cursor_roundtrip_and_malformed_input(read_at):
    item = SimpleNamespace(published_at=datetime.now(UTC), id=uuid4(), read_at=read_at)
    assert decode_cursor(encode_cursor(item)) == (read_at is None, item.published_at, item.id)
    bad_uuid = base64.urlsafe_b64encode(
        json.dumps([True, item.published_at.isoformat(), 123]).encode()
    )
    for cursor in ["!invalid", "a" * 301, "bnVsbA==", "e30=", "W10=", bad_uuid.decode()]:
        with pytest.raises(HTTPException) as failure:
            decode_cursor(cursor)
        assert failure.value.status_code == 422
