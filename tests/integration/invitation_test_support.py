"""Controlled business clock and captured transport for cross-repository integration only."""

import json
import os
from datetime import datetime
from pathlib import Path

from src.adapters.storage.postgres.invitations import InvitationRepository
from src.bootstrap.database import get_session_maker
from src.core.exteriorization.models import PushResult


def clock_path() -> Path:
    return Path(os.environ["INVITATIONS_FLOW_DIRECTORY"]) / "clock.txt"


def controlled_now() -> datetime:
    return datetime.fromisoformat(clock_path().read_text().strip())


class ControlledInvitationRepository(InvitationRepository):
    async def now(self, session) -> datetime:
        return controlled_now()


def invitation_repository() -> ControlledInvitationRepository:
    return ControlledInvitationRepository(get_session_maker())


class CapturedPush:
    async def send(self, subscription: dict, payload: dict, ttl: int) -> PushResult:
        directory = Path(os.environ["INVITATIONS_FLOW_DIRECTORY"])
        # No external push HTTP request is made by this test-only adapter.
        marker = directory / f"attempt-{payload['invitation_id']}"
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            result = PushResult(accepted=True)
        else:
            os.close(descriptor)
            result = PushResult(retryable=True, code="push_transient_error")
        raw = json.dumps({"payload": payload, "ttl": ttl, "accepted": result.accepted}) + "\n"
        descriptor = os.open(
            directory / "push.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            os.write(descriptor, raw.encode())
        finally:
            os.close(descriptor)
        return result
