"""OpenAI adapter for the title extractor's own structured contract."""

from src.adapters.providers.openai.client import AsyncProvider
from src.core.extractors.contracts import ProviderMetadata
from src.core.extractors.document_title import DocumentTitle


class DocumentTitleProviderError(RuntimeError):
    pass


class OpenAIDocumentTitleProvider(AsyncProvider):
    provider_name = "openai"

    def __init__(
        self, api_key, model, client=None, *, timeout_seconds, max_concurrency, max_retries=2
    ):
        self._api_key, self.model_name = api_key, model or "unconfigured"
        self._max_retries = max_retries
        self._configure_client(client, timeout_seconds, max_concurrency)

    async def extract(self, document, profile):
        if self._client is None:
            if not self._api_key or self.model_name == "unconfigured":
                from src.core.processing.errors import WorkflowFailure

                raise WorkflowFailure("provider_configuration", retryable=True)
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
            )
        try:
            async with self._request_slot():
                response = await self._client.responses.parse(
                    model=self.model_name,
                    input=[
                        {"role": "system", "content": profile.instructions},
                        {"role": "user", "content": document.content},
                    ],
                    text_format=DocumentTitle,
                    store=False,
                )
            if response.output_parsed is None:
                raise DocumentTitleProviderError("OpenAI did not return a structured title")
            payload = DocumentTitle.model_validate(response.output_parsed)
        except DocumentTitleProviderError:
            raise
        except Exception as error:
            raise DocumentTitleProviderError("OpenAI title extraction failed") from error
        usage = getattr(response, "usage", None)
        return payload, ProviderMetadata(
            provider=self.provider_name,
            model=getattr(response, "model", self.model_name),
            response_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
