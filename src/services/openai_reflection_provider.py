"""OpenAI adapter for structured, evidence-bound reflections."""

import json
import logging
from typing import Any

from src.reflection.contracts import ReflectionContext, ReflectionResult
from src.reflection.profiles import ReflectionProfile
from src.services.async_provider import AsyncProvider
from src.services.reflection_provider import (
    ProviderReflection,
    ReflectionProviderError,
)
from src.services.structured_extractor import TokenUsage

logger = logging.getLogger(__name__)


class OpenAIReflectionProvider(AsyncProvider):
    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str | None, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model or "unconfigured"
        self._configure_client(client)

    async def reflect(
        self, context: ReflectionContext, profile: ReflectionProfile
    ) -> ProviderReflection:
        client = self._get_client()
        try:
            logger.info(
                "openai_reflection_request_started model=%s claims=%s relations=%s",
                self.model_name,
                len(context.claims),
                len(context.relations),
            )
            async with self._request_slot():
                response = await client.responses.parse(
                    model=self.model_name,
                    input=[
                        {"role": "system", "content": profile.instructions},
                        {
                            "role": "user",
                            "content": (
                                "Question:\n"
                                f"{context.question}\n\n"
                                "Evidence-bound context (JSON):\n"
                                f"{json.dumps(context.model_dump(mode='json'), ensure_ascii=False)}"
                            ),
                        },
                    ],
                    text_format=ReflectionResult,
                )
        except Exception as error:
            logger.exception(
                "openai_reflection_request_failed model=%s claims=%s relations=%s error_type=%s",
                self.model_name,
                len(context.claims),
                len(context.relations),
                type(error).__name__,
            )
            raise ReflectionProviderError("OpenAI reflection request failed") from error

        if response.output_parsed is None:
            raise ReflectionProviderError("OpenAI did not return a structured reflection")
        try:
            result = ReflectionResult.model_validate(response.output_parsed)
        except Exception as error:
            raise ReflectionProviderError("OpenAI returned an invalid reflection") from error
        usage = getattr(response, "usage", None)
        logger.info(
            "openai_reflection_request_completed model=%s input_tokens=%s output_tokens=%s",
            getattr(response, "model", self.model_name),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )
        return ProviderReflection(
            result=result,
            provider=self.provider_name,
            model=getattr(response, "model", self.model_name),
            response_id=getattr(response, "id", None),
            usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            ),
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key or self.model_name == "unconfigured":
            raise ReflectionProviderError(
                "OpenAI reflection requires OPENAI_API_KEY and OPENAI_MODEL"
            )
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self._api_key, timeout=self._timeout)
        return self._client
