"""Best-effort, bounded title scheduling as authenticated users read their originals."""

import logging

from src.config import get_settings
from src.use_cases.backfill_document_titles import BackfillDocumentTitles

logger = logging.getLogger(__name__)


class EnsureDocumentTitles:
    def __init__(self, repository, runtime):
        self.backfill = BackfillDocumentTitles(repository, runtime)

    async def execute(self, documents):
        settings = get_settings()
        limit = settings.document_title_read_limit
        if (
            not limit
            or settings.llm_provider != "openai"
            or not settings.openai_model
            or not settings.openai_api_key
        ):
            return
        missing = [
            document.id
            for document in documents
            if not document.title or not document.title.strip()
        ]
        queued = 0
        try:
            # Batch-filter prior work so terminal failures cannot starve later notes.
            for offset in range(0, len(missing), 100):
                ids = missing[offset : offset + 100]
                blocked = await self.backfill.unavailable(ids)
                for document_id in ids:
                    if document_id in blocked:
                        continue
                    result = await self.backfill.execute(
                        document_id, apply=True, retry_failed=False
                    )
                    if result.status == "queued":
                        queued += 1
                        if queued >= limit:
                            return
        except Exception as error:
            # Scheduling must never make readable originals unavailable. Do not log text/config.
            logger.warning(
                "Title scheduling unavailable: workspace=%s error_type=%s",
                self.backfill.owner,
                type(error).__name__,
            )
