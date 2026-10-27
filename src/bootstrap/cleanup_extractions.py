"""Compose explicit maintenance commands with platform SQL and migration resources."""

from contextlib import asynccontextmanager

from src.adapters.access.cli.cleanup_extractions import main as run
from src.adapters.storage.arcadedb.migrations import MigrationGraph
from src.adapters.storage.postgres.migrations import PostgresMigrations
from src.bootstrap.data_migrations import MigrationResources
from src.bootstrap.database import close_database, get_session_maker
from src.bootstrap.settings import get_settings
from src.bootstrap.workflows import worker_runtime
from src.use_cases.maintenance.cleanup_extractions import CleanupExtractions


class WorkspaceCleanupResources(MigrationResources):
    @asynccontextmanager
    async def open(self, workspace):
        async with worker_runtime(workspace.user_id) as runtime:
            yield (
                MigrationGraph(runtime.graph_store._client, runtime.graph_store),
                self.files(workspace),
            )


def create_cleanup():
    settings = get_settings()
    return CleanupExtractions(
        PostgresMigrations(
            get_session_maker(), settings.arcadedb_instance_key, settings.processing_lease_seconds
        ),
        WorkspaceCleanupResources(settings),
        settings.arcadedb_instance_key,
    )


def main():
    run(create_cleanup, close_database)


if __name__ == "__main__":
    main()
