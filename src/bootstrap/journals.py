"""Journal application composition; no new process or provider lifecycle."""

from src.adapters.storage.postgres.journals import PostgresJournals
from src.bootstrap.database import get_session_maker
from src.bootstrap.settings import get_settings
from src.core.journals.preparation_catalog import PREPARATION_TEMPLATE_V2, PREPARATION_TEMPLATE_V3
from src.core.journals.templates import PREPARATION_TEMPLATE
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals
from src.use_cases.journals.reconcile import InstallJournalTemplates, ReconcileJournals


def build_journals(sessions=None):
    return PostgresJournals(sessions if sessions is not None else get_session_maker())


def build_journal_management(sessions=None):
    return ManageJournals(build_journals(sessions), enabled=get_settings().journals_enabled)


def build_journal_queries(sessions=None):
    return QueryJournals(build_journals(sessions), enabled=get_settings().journals_enabled)


async def reconcile_journals():
    if not get_settings().journals_enabled:
        return 0
    repository = build_journals()
    await InstallJournalTemplates(repository).execute(
        (PREPARATION_TEMPLATE, PREPARATION_TEMPLATE_V2, PREPARATION_TEMPLATE_V3)
    )
    return await ReconcileJournals(repository).execute()
