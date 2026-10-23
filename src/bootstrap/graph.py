"""Construct workspace-bound graph adapters with explicit transport configuration."""

from src.adapters.storage.arcadedb.client import AsyncArcadeDBHTTPClient
from src.adapters.storage.arcadedb.graph import ArcadeDBGraphStore
from src.config import get_settings


def build_graph_client(http_url, database, username, password, *, client=None):
    settings = get_settings()
    return AsyncArcadeDBHTTPClient(
        http_url,
        database,
        username,
        password,
        client=client,
        timeout_seconds=settings.graph_timeout_seconds,
        max_connections=settings.graph_max_connections,
    )


def build_graph_store(http_url, database, username, password, *, client=None):
    return ArcadeDBGraphStore(client or build_graph_client(http_url, database, username, password))
