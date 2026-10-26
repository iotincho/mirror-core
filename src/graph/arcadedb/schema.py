"""External mirror-deploy entrypoint; remove after its commands migrate to bootstrap."""

from src.bootstrap.graph_schema import main as main

if __name__ == "__main__":
    raise SystemExit(main())
