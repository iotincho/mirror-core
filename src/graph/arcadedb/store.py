"""Compatibility imports; use the canonical layers for new code."""

from src.adapters.storage.arcadedb.graph import ArcadeDBCommandClient as ArcadeDBCommandClient
from src.adapters.storage.arcadedb.graph import ArcadeDBStoreClient as ArcadeDBStoreClient


def ArcadeDBGraphStore(http_url, database, username, password, *, client=None):
    from src.bootstrap.graph import build_graph_store

    return build_graph_store(http_url, database, username, password, client=client)
