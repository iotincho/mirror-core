"""Process newly supplied material into an extracted, auditable document."""

import logging

from pydantic import BaseModel, ConfigDict

from src.domain.documents import Document, NewDocument
from src.services.extraction_store import ExtractionRun
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument
from src.use_cases.ingest_document import IngestDocument

logger = logging.getLogger(__name__)


class ProcessedDocument(BaseModel):
    """The stored original material and the extraction generated from it."""

    model_config = ConfigDict(frozen=True)

    document: Document
    extraction: ExtractionRun


class IngestAndExtractDocument:
    """Persist input, then immediately run the default extraction profile."""

    def __init__(
        self,
        ingest_document: IngestDocument,
        extract_document: ExtractPersistAndEmbedDocument,
    ) -> None:
        self._ingest_document = ingest_document
        self._extract_document = extract_document

    async def execute(self, new_document: NewDocument) -> ProcessedDocument:
        document = await self._ingest_document.execute(new_document)
        return await self.process_existing(document.id)

    async def process_existing(self, document_id: object) -> ProcessedDocument:
        """Process an already persisted document without creating a duplicate."""
        document = await self._ingest_document.get(document_id)
        extraction = await self._extract_document.execute(document.id)
        if extraction.result is not None:
            logger.info(
                "extraction_completed document_id=%s run_id=%s result=%s",
                document.id,
                extraction.id,
                extraction.result.model_dump_json(),
            )
        return ProcessedDocument(
            document=await self._ingest_document.get(document.id), extraction=extraction
        )
