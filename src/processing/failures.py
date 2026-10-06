"""Map provider/transport failures to safe workflow-owned retry decisions."""

import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from src.processing.artifacts import ArtifactCorrupted
from src.processing.execution import WorkflowFailure
from src.services.document_store import DocumentNotFoundError
from src.use_cases.extract_document import ExtractionEvidenceError
from src.workspaces.secrets import WorkspaceSecretError


def failure_for(error, attempts, service):
    chain, current = [], error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__
    if any(isinstance(item, WorkspaceSecretError) for item in chain):
        return WorkflowFailure("workspace_credentials_unavailable", retryable=True)
    if any(isinstance(item, (DocumentNotFoundError, FileNotFoundError)) for item in chain):
        return WorkflowFailure("original_missing")
    if any(isinstance(item, ArtifactCorrupted) for item in chain):
        return WorkflowFailure("artifact_corrupted")
    if any(isinstance(item, ExtractionEvidenceError) for item in chain):
        return WorkflowFailure("invalid_evidence", retry_delay=0 if attempts < 2 else None)
    for item in chain:
        response = getattr(item, "response", None)
        status = getattr(item, "status_code", None) or getattr(response, "status_code", None)
        if status:
            if status == 429 or status in {408, 409} or status >= 500:
                delay = retry_delay(attempts)
                retry_after = response.headers.get("Retry-After") if response is not None else None
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(
                                delay,
                                (
                                    parsedate_to_datetime(retry_after) - datetime.now(UTC)
                                ).total_seconds(),
                            )
                        except (ValueError, TypeError):
                            pass
                return WorkflowFailure(f"{service}_unavailable", retry_delay=delay)
            return WorkflowFailure(f"{service}_rejected")
    if any(
        isinstance(item, (httpx.TransportError, ConnectionError, TimeoutError, OSError))
        or type(item).__name__ in {"APIConnectionError", "APITimeoutError"}
        for item in chain
    ):
        return WorkflowFailure(f"{service}_unavailable", retry_delay=retry_delay(attempts))
    return WorkflowFailure(f"{service}_invalid_response")


def retry_delay(attempts):
    return (10, 30, 120)[min(max(attempts - 1, 0), 2)] * random.uniform(0.8, 1.2)
