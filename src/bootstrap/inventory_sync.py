"""Compose the metadata synchronizer separately from either HTTP application."""

from src.adapters.access.cli.inventory import main
from src.adapters.storage.filesystem.inventory import FileInventory
from src.adapters.storage.postgres.inventory import PostgresInventory
from src.bootstrap.admin_database import close_admin_database, get_admin_sessions
from src.bootstrap.administration_settings import get_admin_settings
from src.use_cases.administration.sync_inventory import SyncInventory as InventoryCase


def SyncInventory(sessions, root):
    return InventoryCase(PostgresInventory(sessions), FileInventory(root))


def create_sync():
    return SyncInventory(get_admin_sessions(), get_admin_settings().workspaces_path)


if __name__ == "__main__":
    main(create_sync, close_admin_database)
