"""OpenAI implementation of the structured extraction port."""

from typing import Any

from src.domain.documents import Document
from src.extraction.contracts import ExtractionResult
from src.extraction.profiles import ExtractionProfile
from src.services.async_provider import AsyncProvider
from src.services.structured_extractor import (
    ExtractionProviderError,
    ProviderExtraction,
    TokenUsage,
)


class OpenAIExtractor(AsyncProvider):
    """Use OpenAI Responses structured parsing without leaking SDK types outward."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        client: Any | None = None,
        *,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self.model_name = model or "unconfigured"
        self._configure_client(client)
        self._sdk_max_retries = max_retries

    async def extract(self, document: Document, profile: ExtractionProfile) -> ProviderExtraction:
        client = self._get_client()
        try:
            async with self._request_slot():
                response = await client.responses.parse(
                    model=self.model_name,
                    input=[
                        {"role": "system", "content": profile.instructions},
                        {
                            "role": "user",
                            "content": (
                                f"Document ID: {document.id}\n"
                                "<document>\n"
                                f"{document.content}\n"
                                "</document>"
                            ),
                        },
                    ],
                    text_format=ExtractionResult,
                )
        except Exception as error:
            raise ExtractionProviderError("OpenAI extraction request failed") from error

        if response.output_parsed is None:
            raise ExtractionProviderError("OpenAI did not return a structured extraction")

        try:
            result = ExtractionResult.model_validate(response.output_parsed)
        except Exception as error:
            raise ExtractionProviderError("OpenAI returned an invalid extraction") from error

        usage = getattr(response, "usage", None)
        return ProviderExtraction(
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
            raise ExtractionProviderError("OpenAI requires OPENAI_API_KEY and OPENAI_MODEL")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=self._api_key, timeout=self._timeout, max_retries=self._sdk_max_retries
        )
        return self._client
