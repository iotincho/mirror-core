"""Safe workflow retry policy over normalized failure facts."""

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from src.core.processing.errors import WorkflowFailure


@dataclass(frozen=True)
class FailureFacts:
    workspace_credentials: bool = False
    transcoder_unavailable: bool = False
    original_missing: bool = False
    artifact_corrupted: bool = False
    status: int | None = None
    retry_after: str | None = None
    transport_unavailable: bool = False


def retry_delay(attempts):
    return (10, 30, 120)[min(max(attempts - 1, 0), 2)] * random.uniform(0.8, 1.2)


def classify_failure(facts: FailureFacts, attempts, service):
    if facts.workspace_credentials:
        return WorkflowFailure("workspace_credentials_unavailable", retryable=True)
    if facts.transcoder_unavailable:
        return WorkflowFailure("transcription_configuration", retryable=True)
    if facts.original_missing:
        return WorkflowFailure("original_missing")
    if facts.artifact_corrupted:
        return WorkflowFailure("artifact_corrupted")
    if facts.status:
        if facts.status == 429 or facts.status in {408, 409} or facts.status >= 500:
            delay = retry_delay(attempts)
            if facts.retry_after:
                try:
                    delay = max(delay, float(facts.retry_after))
                except ValueError:
                    try:
                        delay = max(
                            delay,
                            (
                                parsedate_to_datetime(facts.retry_after) - datetime.now(UTC)
                            ).total_seconds(),
                        )
                    except (ValueError, TypeError):
                        pass
            return WorkflowFailure(f"{service}_unavailable", retry_delay=delay)
        return WorkflowFailure(f"{service}_rejected")
    if facts.transport_unavailable:
        return WorkflowFailure(f"{service}_unavailable", retry_delay=retry_delay(attempts))
    return WorkflowFailure(f"{service}_invalid_response")
