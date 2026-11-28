"""Ownership and concurrency for lazily-created asynchronous provider clients."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from src.adapters.providers.openai.usage import MeteredOpenAIHttpClient, openai_operation


class AsyncProvider:
    """An injected client is borrowed; an adapter-created client is closed by its host."""

    def _configure_client(
        self, client: Any | None, timeout_seconds: float, max_concurrency: int
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout_seconds
        self._max_concurrency = max_concurrency
        self._semaphore: asyncio.Semaphore | None = None

    def _openai_client(self, api_key, *, max_retries):
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=api_key,
            timeout=self._timeout,
            max_retries=max_retries,
            http_client=MeteredOpenAIHttpClient(timeout=self._timeout),
        )

    @asynccontextmanager
    async def _request_slot(self, feature: str, model: str):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        async with self._semaphore:
            with openai_operation(feature, model):
                yield

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                await self._client.close()
            finally:
                self._client = None
        self._semaphore = None
