"""Recover and publish transactional outbox entries, independently of HTTP."""

import asyncio
import logging
import signal

from src.adapters.storage.postgres.submissions import SubmissionRepository
from src.bootstrap.acceptance import recover_submissions
from src.bootstrap.database import close_database
from src.bootstrap.invitations import get_invitation_repository
from src.bootstrap.messaging import broker
from src.bootstrap.notifications import get_notifications
from src.bootstrap.observability import initialize_sentry, report_issue, trace_operation
from src.bootstrap.processing import get_repository
from src.bootstrap.recovery import get_recovery_repository
from src.bootstrap.settings import get_settings
from src.bootstrap.worker import execute_processing
from src.bootstrap.workflows import worker_runtime
from src.use_cases.expire_axis_previews import expire_axis_previews
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations

logger = logging.getLogger(__name__)


async def dispatch_once(repository, publish):
    from src.adapters.storage.postgres.state import PostgresExecutionStore
    from src.use_cases.processing.dispatch import dispatch_once as dispatch

    return await dispatch(PostgresExecutionStore(repository), publish, report_issue=report_issue)


async def main():
    logging.basicConfig(level=logging.INFO)
    initialize_sentry("processing-dispatcher")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    connected = False
    try:
        while not stop.is_set():
            try:
                repository = get_repository()
                try:
                    await expire_axis_previews(repository, get_settings())
                except Exception as error:
                    report_issue("axis_preview_cleanup_failed", error)
                    logger.warning("Axis preview cleanup deferred")
                await get_recovery_repository().cleanup()
                await ScheduleInvitations(get_invitation_repository()).execute()
                await get_notifications().distribute()
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
                with trace_operation("processing.dispatch"):
                    await dispatch_once(repository, execute_processing.kiq)
            except Exception as error:
                report_issue("dispatcher_unavailable", error)
                logger.warning("Dispatcher unavailable; pending work remains in PostgreSQL")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
    finally:
        if connected:
            await broker.shutdown()
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
