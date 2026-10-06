"""Compatibility entrypoint; the operational CLI is packaged in the runtime image."""

from src.maintenance.cleanup_extractions import main

if __name__ == "__main__":
    main()
