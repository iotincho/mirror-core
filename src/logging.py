"""Small, consistent logging setup for local development and tests."""

import logging
from contextvars import ContextVar

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    """Attach request context, including logs emitted in worker threads."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def configure_logging(level: str) -> None:
    """Configure application logging once, without changing third-party loggers."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s: %(message)s",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestContextFilter())
