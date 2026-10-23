"""Compatibility imports; use the canonical layers for new code."""

from src.adapters.storage.arcadedb.client import ArcadeDBClientError as ArcadeDBClientError
from src.adapters.storage.arcadedb.client import ArcadeDBHTTPClient as ArcadeDBHTTPClient
from src.adapters.storage.arcadedb.client import ArcadeDBTransaction as ArcadeDBTransaction
from src.adapters.storage.arcadedb.client import (
    AsyncArcadeDBTransaction as AsyncArcadeDBTransaction,
)


def AsyncArcadeDBHTTPClient(http_url, database, username, password, *, client=None):
    from src.bootstrap.graph import build_graph_client

    return build_graph_client(http_url, database, username, password, client=client)
