"""Explicit broker configuration shared by worker and dispatcher entrypoints."""

from src.adapters.messaging.rabbitmq.broker import create_broker
from src.config import get_settings

settings = get_settings()
broker = create_broker(
    settings.rabbitmq_url, settings.processing_concurrency, settings.processing_queue_name
)
