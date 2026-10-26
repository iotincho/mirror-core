"""External mirror-deploy entrypoint; remove after its commands migrate to bootstrap."""

from src.bootstrap.data_migrations import DataMigrations as DataMigrations
from src.bootstrap.data_migrations import main as main

if __name__ == "__main__":
    main()
