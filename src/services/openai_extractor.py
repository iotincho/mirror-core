"""OpenAI implementation of the structured extraction port."""

import logging
from time import perf_counter
from typing import Any

from src.domain.documents import Document
from src.extraction.contracts import ExtractionResult
from src.extraction.profiles import ExtractionProfile
from src.services.provider_diagnostics import provider_error_details
from src.services.structured_extractor import (
    ExtractionProviderError,
    ProviderExtraction,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class OpenAIExtractor:
    """Use OpenAI Responses structured parsing without leaking SDK types outward."""

    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str | None, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model or "unconfigured"
        self._client = client

    def extract(self, document: Document, profile: ExtractionProfile) -> ProviderExtraction:
        started = perf_counter()
        stage = "configuration"
        try:
            logger.info(
                "openai_extraction_started document_id=%s model=%s profile=%s content_chars=%s",
                document.id, self.model_name, profile.name, len(document.content),
            )
            client = self._get_client()
            stage = "request"
            response = client.responses.parse(
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
            stage = "response_validation"
            if response.output_parsed is None:
                raise ExtractionProviderError("OpenAI did not return a structured extraction")
            result = ExtractionResult.model_validate(response.output_parsed)
        except Exception as error:
            logger.exception(
                "openai_extraction_failed document_id=%s model=%s profile=%s stage=%s "
                "duration_ms=%.1f diagnostics=%s",
                document.id, self.model_name, profile.name, stage,
                (perf_counter() - started) * 1000, provider_error_details(error),
            )
            if isinstance(error, ExtractionProviderError):
                raise
            raise ExtractionProviderError("OpenAI extraction request failed") from error

        usage = getattr(response, "usage", None)
        logger.info(
            "openai_extraction_completed document_id=%s model=%s upstream_request_id=%s "
            "response_id=%s duration_ms=%.1f input_tokens=%s output_tokens=%s",
            document.id, getattr(response, "model", self.model_name),
            getattr(response, "_request_id", None), getattr(response, "id", None),
            (perf_counter() - started) * 1000,
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
        )
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

        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
