"""Durable RabbitMQ transport. PostgreSQL remains the result backend."""

from taskiq_aio_pika import AioPikaBroker

from src.config import get_settings

settings = get_settings()
broker = AioPikaBroker(
    settings.rabbitmq_url,
    qos=settings.processing_concurrency,
    exchange_name=settings.processing_queue_name,
    queue_name=settings.processing_queue_name,
    declare_exchange_kwargs={"durable": True},
    declare_queues_kwargs={"durable": True},
    timeout=10,
)
