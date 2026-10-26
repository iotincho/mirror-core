"""External mirror-deploy entrypoint; remove after its commands migrate to bootstrap."""

from src.bootstrap.inventory_sync import main as main

if __name__ == "__main__":
    main()
