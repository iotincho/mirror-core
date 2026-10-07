"""OpenAI adapter for the emotion layer's own schema."""

from src.extractors.contracts import ProviderMetadata
from src.extractors.emotions import Emotions
from src.services.async_provider import AsyncProvider


class EmotionProviderError(RuntimeError):
    pass


class OpenAIEmotionProvider(AsyncProvider):
    provider_name = "openai"

    def __init__(self, api_key, model, client=None, *, max_retries=2):
        self._api_key, self.model_name = api_key, model or "unconfigured"
        self._max_retries = max_retries
        self._configure_client(client)

    async def extract(self, document, profile):
        if self._client is None:
            if not self._api_key or self.model_name == "unconfigured":
                raise EmotionProviderError("OpenAI requires OPENAI_API_KEY and OPENAI_MODEL")
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
                    text_format=Emotions,
                    store=False,
                )
            if response.output_parsed is None:
                raise EmotionProviderError("OpenAI did not return a structured emotion result")
            payload = Emotions.model_validate(response.output_parsed)
        except EmotionProviderError:
            raise
        except Exception as error:
            raise EmotionProviderError("OpenAI emotion extraction failed") from error
        usage = getattr(response, "usage", None)
        return payload, ProviderMetadata(
            provider=self.provider_name,
            model=getattr(response, "model", self.model_name),
            response_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
