"""Root-only provisioning; runtime principals remain restricted to one database."""

import asyncio

from src.adapters.storage.arcadedb.administration import ArcadeDBAdminClient
from src.adapters.storage.arcadedb.client import ArcadeDBHTTPClient
from src.adapters.storage.arcadedb.schema import apply_schema


class ArcadeDBProvisioning:
    def __init__(self, http_url, username, password):
        self.http_url, self.username, self.password = http_url, username, password

    async def provision(self, target, secret):
        await asyncio.to_thread(self._provision, target, secret)

    def _provision(self, target, secret):
        admin = ArcadeDBAdminClient(self.http_url, self.username, self.password)
        admin.ensure_database(target.database_name)
        apply_schema(ArcadeDBHTTPClient(
            self.http_url, target.database_name, self.username, self.password,
        ))
        admin.ensure_runtime_principal(
            database_name=target.database_name, username=target.graph_username, password=secret,
        )
        admin.verify_runtime_principal(
            database_name=target.database_name, username=target.graph_username, password=secret,
        )
