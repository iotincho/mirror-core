"""Compose deployment migrations without touching an environment on import."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from src.adapters.storage.arcadedb.administration import ArcadeDBAdminClient
from src.adapters.storage.arcadedb.migrations import MigrationGraph
from src.adapters.storage.filesystem.migrations import MigrationFiles
from src.adapters.storage.postgres.migrations import PostgresMigrations
from src.bootstrap.database import close_database, get_session_maker
from src.bootstrap.graph import build_graph_client, build_graph_store
from src.bootstrap.settings import get_settings
from src.core.maintenance.models import MIGRATION_ID
from src.use_cases.maintenance.data_migrations import DataMigrations as Case
from src.use_cases.maintenance.extraction_cleanup import LegacyExtractionCleanup as CleanupCase


class MigrationResources:
    def __init__(self, settings, admin=None):
        self.settings = settings
        self.admin = admin or ArcadeDBAdminClient(
            settings.arcadedb_http_url, settings.arcadedb_username, settings.arcadedb_password
        )

    def files(self, workspace):
        return MigrationFiles(self.settings.workspaces_path / str(workspace.user_id))

    async def exists(self, workspace):
        return await asyncio.to_thread(self.admin.database_exists, workspace.database_name)

    @asynccontextmanager
    async def open(self, workspace):
        settings = self.settings
        client = build_graph_client(
            settings.arcadedb_http_url,
            workspace.database_name,
            settings.arcadedb_username,
            settings.arcadedb_password,
        )
        graph = build_graph_store(
            settings.arcadedb_http_url,
            workspace.database_name,
            settings.arcadedb_username,
            settings.arcadedb_password,
            client=client,
        )
        try:
            yield MigrationGraph(client, graph), self.files(workspace)
        finally:
            await graph.close()


def DataMigrations(sessions, settings, backup_root=None, *, admin=None):
    backup_root = Path(backup_root or settings.workspaces_path.parent / "migration-backups")
    instance = hashlib.sha256(settings.arcadedb_instance_key.encode()).hexdigest()[:16]
    return Case(
        PostgresMigrations(
            sessions, settings.arcadedb_instance_key, settings.processing_lease_seconds
        ),
        MigrationResources(settings, admin),
        settings.arcadedb_instance_key,
        lambda workspace: backup_root / MIGRATION_ID / instance / str(workspace.user_id),
    )


def LegacyExtractionCleanup(client, root):
    return CleanupCase(MigrationGraph(client, None), MigrationFiles(root))


def main():
    from src.adapters.access.cli.data_migrations import main as run

    run(lambda backup: DataMigrations(get_session_maker(), get_settings(), backup), close_database)


if __name__ == "__main__":
    main()
