"""OpenAI implementation of the speech-to-text port."""

from typing import Any

from src.adapters.providers.openai.client import AsyncProvider
from src.core.audio.ports import TranscriptionProviderError


class OpenAITranscriptionProvider(AsyncProvider):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        client: Any | None = None,
        *,
        timeout_seconds,
        max_concurrency,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self.model_name = model
        self._configure_client(client, timeout_seconds, max_concurrency)
        self._sdk_max_retries = max_retries

    async def transcribe(self, source) -> str:
        client = self._get_client()
        try:
            async with self._request_slot():
                # Transcode WebM off the event loop; retain only bytes during SDK retries.
                upload = await source.prepare(timeout=self._timeout)
                response = await client.audio.transcriptions.create(
                    model=self.model_name,
                    file=(upload.filename, upload.content),
                )
            transcript = response.text
        except Exception as error:
            raise TranscriptionProviderError("OpenAI transcription request failed") from error
        if not isinstance(transcript, str) or not transcript.strip():
            raise TranscriptionProviderError("OpenAI returned an empty transcription")
        return transcript

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise TranscriptionProviderError("OpenAI requires OPENAI_API_KEY")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=self._api_key, timeout=self._timeout, max_retries=self._sdk_max_retries
        )
        return self._client
