"""Recover and publish transactional outbox entries, independently of HTTP."""

import asyncio
import logging
import signal

from src.dependencies import close_provider_clients
from src.processing.broker import broker
from src.processing.repository import ProcessingRepository
from src.processing.runtime import get_repository
from src.processing.submissions import SubmissionRepository
from src.processing.tasks import execute_processing
from src.processing.workflows import worker_runtime
from src.use_cases.submit_processing import recover_submissions
from src.user_management.database import close_database

logger = logging.getLogger(__name__)


async def dispatch_once(repository: ProcessingRepository, publish) -> int:
    rows = await repository.claim_outbox()
    for row in rows:
        try:
            await asyncio.wait_for(publish(str(row.processing_id), row.generation), timeout=20)
        except Exception:
            # Avoid logging broker URLs, credentials or document content.
            logger.warning("Outbox delivery postponed: %s", row.id)
            await repository.settle_outbox(row, published=False)
        else:
            # aio-pika uses publisher confirms; a crash here can cause duplicates.
            await repository.settle_outbox(row, published=True)
    return len(rows)


async def main():
    logging.basicConfig(level=logging.INFO)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    connected = False
    try:
        while not stop.is_set():
            try:
                repository = get_repository()
                await repository.recover()
                await repository.recover_parents()
                await recover_submissions(SubmissionRepository(repository), worker_runtime)
                if not connected:
                    try:
                        await broker.startup()
                        connected = True
                    except Exception:
                        await broker.shutdown()
                        raise
                await dispatch_once(repository, execute_processing.kiq)
            except Exception:
                logger.warning("Dispatcher unavailable; pending work remains in PostgreSQL")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
    finally:
        if connected:
            await broker.shutdown()
        await close_provider_clients()
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
