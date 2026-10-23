"""Normalize transport/SDK exception chains without passing their payloads to policy."""

import httpx

from src.core.audio.errors import AudioTranscoderUnavailable
from src.core.documents.ports import DocumentNotFoundError
from src.core.extractors.artifacts import ArtifactCorrupted
from src.core.processing.failures import FailureFacts
from src.core.workspaces.errors import WorkspaceSecretError


def failure_facts(error):
    chain, current = [], error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__
    status = retry_after = None
    for item in chain:
        response = getattr(item, "response", None)
        status = getattr(item, "status_code", None) or getattr(response, "status_code", None)
        if status:
            retry_after = response.headers.get("Retry-After") if response is not None else None
            break
    return FailureFacts(
        workspace_credentials=any(isinstance(item, WorkspaceSecretError) for item in chain),
        transcoder_unavailable=any(isinstance(item, AudioTranscoderUnavailable) for item in chain),
        original_missing=any(
            isinstance(item, (DocumentNotFoundError, FileNotFoundError)) for item in chain
        ),
        artifact_corrupted=any(isinstance(item, ArtifactCorrupted) for item in chain),
        status=status,
        retry_after=retry_after,
        transport_unavailable=any(
            isinstance(item, (httpx.TransportError, ConnectionError, TimeoutError, OSError))
            or type(item).__name__ in {"APIConnectionError", "APITimeoutError"}
            for item in chain
        ),
    )
