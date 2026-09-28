"""OpenAI implementation of the speech-to-text port."""

from pathlib import Path
from typing import Any

from src.services.transcription_provider import TranscriptionProviderError


class OpenAITranscriptionProvider:
    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model
        self._client = client

    def transcribe(self, audio_path: Path) -> str:
        client = self._get_client()
        try:
            with audio_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=self.model_name,
                    file=audio_file,
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
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)
        return self._client
