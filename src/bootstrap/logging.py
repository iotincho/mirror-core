"""Small, consistent logging setup for local development and tests."""

import logging


def configure_logging(level: str) -> None:
    """Configure application logging once, without changing third-party loggers."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
