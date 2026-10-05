"""OpenAI implementation of the speech-to-text port."""

import asyncio
from pathlib import Path
from typing import Any

from src.services.async_provider import AsyncProvider
from src.services.transcription_provider import TranscriptionProviderError


class OpenAITranscriptionProvider(AsyncProvider):
    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model
        self._configure_client(client)

    async def transcribe(self, audio_path: Path) -> str:
        client = self._get_client()
        try:
            async with self._request_slot():
                # Pass bytes to the SDK so multipart encoding never reads a file on the loop.
                content = await asyncio.to_thread(audio_path.read_bytes)
                response = await client.audio.transcriptions.create(
                    model=self.model_name,
                    file=(audio_path.name, content),
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

        self._client = AsyncOpenAI(api_key=self._api_key, timeout=self._timeout)
        return self._client
