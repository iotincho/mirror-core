"""Compatibility constructor; the title case now uses processing transaction ports."""

from src.core.documents.title_scheduling import TitleBackfillResult as TitleBackfillResult


def BackfillDocumentTitles(repository, runtime):
    from src.bootstrap.processing import build_title_backfill

    return build_title_backfill(repository, runtime)
