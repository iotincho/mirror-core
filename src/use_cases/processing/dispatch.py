"""Publish claimed intentions and settle only confirmed deliveries."""

import asyncio
import logging

from src.core.processing.ports import OutboxStore, ProcessingPublisher

logger = logging.getLogger(__name__)


async def dispatch_once(
    repository: OutboxStore, publish: ProcessingPublisher, *, report_issue
) -> int:
    rows = await repository.claim_outbox()
    for row in rows:
        try:
            await asyncio.wait_for(publish(str(row.processing_id), row.generation), timeout=20)
        except Exception as error:
            report_issue("outbox_delivery_failed", error, processing_id=row.processing_id)
            # Avoid logging broker URLs, credentials or document content.
            logger.warning("Outbox delivery postponed: %s", row.id)
            await repository.settle_outbox(row, published=False)
        else:
            # aio-pika uses publisher confirms; a crash here can cause duplicates.
            await repository.settle_outbox(row, published=True)
    return len(rows)
