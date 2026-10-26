"""Compatibility defaults for providers not yet composed through bootstrap."""

from typing import Any

from src.adapters.providers.openai.client import AsyncProvider as ProviderClient
from src.bootstrap.settings import get_settings


class AsyncProvider(ProviderClient):
    """Keep the legacy constructor while sharing client ownership and concurrency."""

    def _configure_client(self, client: Any | None) -> None:
        settings = get_settings()
        super()._configure_client(
            client, settings.provider_timeout_seconds, settings.provider_max_concurrency
        )
