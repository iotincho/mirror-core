"""Ownership and concurrency for lazily-created asynchronous provider clients."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from src.config import get_settings


class AsyncProvider:
    """An injected client is borrowed; an adapter-created client is closed by its host."""

    def _configure_client(self, client: Any | None) -> None:
        settings = get_settings()
        self._client = client
        self._owns_client = client is None
        self._timeout = settings.provider_timeout_seconds
        self._max_concurrency = settings.provider_max_concurrency
        self._semaphore: asyncio.Semaphore | None = None

    @asynccontextmanager
    async def _request_slot(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        async with self._semaphore:
            yield

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                await self._client.close()
            finally:
                self._client = None
        self._semaphore = None
