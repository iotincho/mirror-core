"""Default processing flow: extraction, graph persistence, then claim embeddings."""

import logging
from uuid import UUID

from src.services.extraction_store import ExtractionRun
from src.use_cases.embed_claims import ClaimEmbeddingFailedError, EmbedClaims
from src.use_cases.embed_documents import DocumentEmbeddingFailedError, EmbedDocument
from src.use_cases.extract_and_persist_document import ExtractAndPersistDocument

logger = logging.getLogger(__name__)


class ExtractPersistAndEmbedDocument:
    """Make every successful extracted claim semantically searchable."""

    def __init__(
        self,
        extract_and_persist: ExtractAndPersistDocument,
        embed_claims: EmbedClaims,
        embed_document: EmbedDocument,
        processing=None,
        user_id=None,
    ) -> None:
        self._extract_and_persist = extract_and_persist
        self._embed_claims = embed_claims
        self._embed_document = embed_document
        self._processing, self._user_id = processing, user_id

    async def execute(self, document_id: UUID, profile_name: str = "v4") -> ExtractionRun:
        if self._processing is not None:
            from src.processing.submissions import SubmissionConflict
            async with self._processing.lock_resource(self._user_id, document_id) as locked:
                if not locked:
                    raise SubmissionConflict("processing_active")
                try:
                    await self._processing.assert_inactive(self._user_id, document_id)
                except ValueError as error:
                    raise SubmissionConflict("processing_active") from error
                return await self._execute(document_id, profile_name)
        return await self._execute(document_id, profile_name)

    async def _execute(self, document_id, profile_name):
        extraction = await self._extract_and_persist.execute(document_id, profile_name)
        document = await self._extract_and_persist.get_document(document_id)
        try:
            count = await self._embed_claims.execute(document, extraction)
            await self._embed_document.execute(document)
        except (ClaimEmbeddingFailedError, DocumentEmbeddingFailedError):
            logger.exception(
                "document_or_claim_embedding_failed document_id=%s run_id=%s",
                document_id,
                extraction.id,
            )
            raise
        logger.info(
            "document_and_claims_embedded document_id=%s run_id=%s claim_count=%s",
            document_id,
            extraction.id,
            count,
        )
        return extraction
