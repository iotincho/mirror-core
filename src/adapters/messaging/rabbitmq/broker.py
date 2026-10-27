"""Durable RabbitMQ transport. PostgreSQL remains the result backend."""

from taskiq_aio_pika import AioPikaBroker


def create_broker(url, concurrency, queue_name):
    return AioPikaBroker(
        url, qos=concurrency, exchange_name=queue_name, queue_name=queue_name,
        declare_exchange_kwargs={"durable": True}, declare_queues_kwargs={"durable": True},
        timeout=10,
    )
