"""Record each OpenAI SDK HTTP attempt before SDK or business validation."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from openai import DefaultAsyncHttpxClient

from src.core.administration.ai_usage import AiUsageAttempt, AiUsageLedger, AiUsageResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Attribution:
    ledger: AiUsageLedger
    user_id: UUID | None
    execution_id: UUID | None
    report_failure: Callable[[], None]
    feature_override: str | None


_attribution = ContextVar[_Attribution | None]("openai_usage_attribution", default=None)
_operation = ContextVar[tuple[str, str] | None]("openai_usage_operation", default=None)


@contextmanager
def attribute_openai_usage(ledger, user_id, *, execution_id, report_failure, feature_override=None):
    token = _attribution.set(
        _Attribution(ledger, user_id, execution_id, report_failure, feature_override)
    )
    try:
        yield
    finally:
        _attribution.reset(token)


@contextmanager
def openai_operation(feature: str, requested_model: str):
    token = _operation.set((feature, requested_model))
    try:
        yield
    finally:
        _operation.reset(token)


def _object(value):
    return value if isinstance(value, dict) else {}


def _identifier(value):
    return (
        value if isinstance(value, str) and 0 < len(value) <= 200 and "\x00" not in value else None
    )


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _duration(value):
    if type(value) not in (int, float) or not 0 <= value < 10**14:
        return None
    return round(Decimal(str(value)), 6)


def _reported_usage(response: httpx.Response, feature: str, *, streamed: bool) -> AiUsageResult:
    payload = {}
    if not streamed:
        try:
            payload = _object(response.json())
        except (ValueError, RecursionError):
            pass  # The SDK still receives the original response.
    usage = _object(payload.get("usage"))
    input_details = _object(usage.get("input_tokens_details"))
    audio_details = _object(usage.get("input_token_details"))
    outcome = (
        "failed"
        if not response.is_success or payload.get("status") in ("failed", "cancelled", "incomplete")
        else "succeeded"
    )
    return AiUsageResult(
        outcome=outcome,
        effective_model=_identifier(payload.get("model")),
        provider_request_id=_identifier(response.headers.get("x-request-id"))
        or _identifier(payload.get("id")),
        input_tokens=_count(usage.get("input_tokens", usage.get("prompt_tokens"))),
        output_tokens=_count(usage.get("output_tokens")),
        total_tokens=_count(usage.get("total_tokens")),
        cached_input_tokens=_count(input_details.get("cached_tokens")),
        audio_input_tokens=_count(audio_details.get("audio_tokens")),
        duration_seconds=(
            _duration(usage.get("seconds", payload.get("duration")))
            if feature == "transcription"
            else None
        ),
    )


async def _write(attribution, operation, *args):
    try:
        async with asyncio.timeout(0.5):
            return await operation(*args)
    except Exception:
        # Storage failures are isolated from provider execution and contain no payload.
        logger.warning("AI usage receipt write failed")
        attribution.report_failure()
        return None


async def _finish(attribution, attempt, started, result):
    if started is None:
        await _write(attribution, attribution.ledger.start, attempt)
    if await _write(attribution, attribution.ledger.finish, attempt.attempt_id, result) is None:
        await _write(attribution, attribution.ledger.finish, attempt.attempt_id, result)


class MeteredOpenAIHttpClient(DefaultAsyncHttpxClient):
    async def send(self, request: httpx.Request, **options) -> httpx.Response:
        attribution, operation = _attribution.get(), _operation.get()
        if attribution is None or operation is None:
            return await super().send(request, **options)

        feature, model = operation
        model = _identifier(model)
        if model is None:
            attribution.report_failure()
            return await super().send(request, **options)
        attempt = AiUsageAttempt(
            attempt_id=uuid4(),
            user_id=attribution.user_id,
            execution_id=attribution.execution_id,
            feature=attribution.feature_override or feature,
            provider="openai",
            requested_model=model,
        )
        started = await _write(attribution, attribution.ledger.start, attempt)
        if started is False:  # No open collection interval.
            return await super().send(request, **options)

        try:
            response = await super().send(request, **options)
        except (Exception, asyncio.CancelledError):
            await _finish(attribution, attempt, started, AiUsageResult(outcome="unknown"))
            raise
        result = _reported_usage(response, feature, streamed=options.get("stream", False))
        await _finish(attribution, attempt, started, result)
        return response
