"""Pure engine/time tests and Web Push adapter contract checks."""

import base64
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from pydantic import ValidationError

from src.api.schemas.exteriorization import PreferenceUpdate
from src.config import Settings
from src.exteriorization.catalog import CATALOG
from src.exteriorization.contracts import EngineContext
from src.exteriorization.engine import select_trigger
from src.exteriorization.repository import InvitationError
from src.exteriorization.scheduling import expires_at, next_occurrence, scheduled_at
from src.exteriorization.web_push import WebPushTransport, validate_subscription


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_catalog_and_rotation_have_stable_general_questions():
    assert len(CATALOG) == len({item.candidate_id for item in CATALOG}) == 12
    now = datetime(2026, 10, 13, tzinfo=UTC)
    context = EngineContext(now, "UTC")
    assert select_trigger(context).candidate_id == "daily_01"
    history = ()
    for _ in range(40):
        trigger = select_trigger(EngineContext(now, "UTC", history), choose=lambda items: items[0])
        assert trigger.candidate_id not in {item.candidate_id for item in history[:7]}
        if history:
            assert trigger.category != history[0].category
        history = (trigger,) + history


def test_filters_relax_without_preventing_selection():
    context = EngineContext(datetime.now(UTC), "UTC", (CATALOG[0],))
    assert select_trigger(context, catalog=(CATALOG[0],)) == CATALOG[0]
    assert select_trigger(context, catalog=CATALOG[:2]).candidate_id == "daily_02"


def test_local_time_and_date_boundary():
    due = scheduled_at(date(2026, 10, 13), "20:30", "America/Argentina/Buenos_Aires")
    assert due == datetime(2026, 10, 13, 23, 30, tzinfo=UTC)
    assert next_occurrence(due, "20:30", "America/Argentina/Buenos_Aires").day == 14
    assert expires_at(due, "America/Argentina/Buenos_Aires") == datetime(
        2026,
        10,
        14,
        1,
        30,
        tzinfo=UTC,
    )
    late = scheduled_at(date(2026, 10, 13), "23:30", "America/Argentina/Buenos_Aires")
    assert expires_at(late, "America/Argentina/Buenos_Aires") == datetime(
        2026,
        10,
        14,
        3,
        tzinfo=UTC,
    )


def test_dst_gap_uses_first_valid_minute_and_fold_uses_first_occurrence():
    assert scheduled_at(date(2026, 3, 8), "02:30", "America/New_York") == datetime(
        2026,
        3,
        8,
        7,
        tzinfo=UTC,
    )
    assert scheduled_at(date(2026, 11, 1), "01:30", "America/New_York") == datetime(
        2026,
        11,
        1,
        5,
        30,
        tzinfo=UTC,
    )
    assert next_occurrence(datetime(2026, 11, 1, 6, tzinfo=UTC), "01:30", "America/New_York") == (
        datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    )


@pytest.mark.parametrize(
    "time,zone", [("24:30", "UTC"), ("1:00", "UTC"), ("20:30", "missing/zone")]
)
def test_configuration_rejects_invalid_times_and_zones(time, zone):
    with pytest.raises(ValidationError):
        PreferenceUpdate(enabled=True, local_time=time, timezone=zone)


def push_keys():
    public = (
        generate_private_key(SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    )

    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    return encode(public), encode(b"a" * 16)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.evil.test/x",
        "https://user@fcm.googleapis.com/x",
    ],
)
def test_subscription_validation_rejects_arbitrary_destinations(endpoint):
    with pytest.raises(InvitationError):
        validate_subscription(endpoint, *push_keys(), ["fcm.googleapis.com"])


def test_valid_subscription_and_key_validation():
    endpoint = "https://fcm.googleapis.com/opaque-endpoint"
    validate_subscription(endpoint, *push_keys(), ["fcm.googleapis.com"])
    with pytest.raises(InvitationError):
        validate_subscription(endpoint, "invalid", "invalid", ["fcm.googleapis.com"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,retryable,expired",
    [
        (410, False, True),
        (404, False, True),
        (429, True, False),
        (503, True, False),
        (403, False, False),
    ],
)
async def test_transport_sanitizes_provider_failures(monkeypatch, status, retryable, expired):
    pywebpush = pytest.importorskip("pywebpush")

    def fail(**kwargs):
        raise pywebpush.WebPushException(
            "SECRET_ENDPOINT_PRIVATE_KEY",
            response=SimpleNamespace(status_code=status),
        )

    monkeypatch.setattr(pywebpush, "webpush", fail)
    transport = WebPushTransport(
        Settings(
            _env_file=None,
            WEB_PUSH_PRIVATE_KEY="private",
            WEB_PUSH_SUBJECT="mailto:test@example.com",
        )
    )
    result = await transport.send({}, {}, 60)
    assert (result.retryable, result.expired) == (retryable, expired)
    assert "SECRET" not in str(result)


@pytest.mark.anyio
async def test_real_webpush_encryption_and_vapid_with_http_boundary_simulated(
    tmp_path, monkeypatch
):
    pytest.importorskip("pywebpush")
    from requests import Response, Session

    from src.exteriorization.vapid import generate_keys

    private, public = generate_keys(tmp_path / "vapid")
    assert private.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        generate_keys(tmp_path / "vapid")
    captures = []

    def accept(self, url, **kwargs):
        captures.append((url, kwargs))
        response = Response()
        response.status_code = 201
        return response

    monkeypatch.setattr(Session, "post", accept)
    p256dh, auth = push_keys()
    transport = WebPushTransport(
        Settings(
            _env_file=None,
            WEB_PUSH_PRIVATE_KEY=str(private),
            WEB_PUSH_PUBLIC_KEY=public.read_text().strip(),
            WEB_PUSH_SUBJECT="mailto:admin@example.com",
        )
    )
    result = await transport.send(
        {"endpoint": "https://fcm.googleapis.com/test", "keys": {"p256dh": p256dh, "auth": auth}},
        {"question": "Private invitation question"},
        57,
    )
    assert result.accepted and len(captures) == 1
    options = captures[0][1]
    assert b"Private invitation question" not in options["data"]
    assert options["headers"]["ttl"] == "57"
    assert "vapid" in options["headers"]["authorization"].lower()
    assert options["allow_redirects"] is False
