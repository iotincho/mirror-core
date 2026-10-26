"""Explicit VAPID CLI entrypoint; never runs during application startup."""

from src.adapters.access.cli.vapid import main
from src.adapters.providers.web_push.vapid import generate_keys as generate_keys

if __name__ == "__main__":
    main(generate_keys)
