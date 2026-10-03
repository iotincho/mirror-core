"""Run one versioned structured extraction without graph persistence."""

import logging
import unicodedata
from uuid import UUID

from src.extraction.contracts import (
    Claim,
    Concept,
    Entity,
    Evidence,
    ExtractionResult,
    Relationship,
)
from src.extraction.profiles import get_profile
from src.services.document_store import DocumentStore
from src.services.extraction_store import ExtractionRun, ExtractionStore, new_extraction_run
from src.services.structured_extractor import StructuredExtractor

logger = logging.getLogger(__name__)


class ExtractionRunFailedError(RuntimeError):
    """Signals that an auditable failed run was recorded."""

    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        super().__init__(f"Extraction run {run_id} failed")


class ExtractionEvidenceError(ValueError):
    """Raised when extracted evidence cannot be traced to the source document."""


class ExtractDocument:
    """Extract evidence-backed knowledge from a stored original document."""

    def __init__(
        self,
        document_store: DocumentStore,
        extraction_store: ExtractionStore,
        extractor: StructuredExtractor,
    ) -> None:
        self._document_store = document_store
        self._extraction_store = extraction_store
        self._extractor = extractor

    def execute(self, document_id: UUID, profile_name: str = "v4") -> ExtractionRun:
        document = self._document_store.get(document_id)
        profile = get_profile(profile_name)
        provider_extraction = None
        try:
            provider_extraction = self._extractor.extract(document, profile)
            result = resolve_evidence(document.content, provider_extraction.result)
            validate_evidence(document.content, result)
            if result.title is not None:
                self._document_store.update_title(document.id, result.title)
        except Exception as error:
            failed_run = new_extraction_run(
                document_id=document.id,
                profile_name=profile.name,
                schema_version=profile.schema_version,
                prompt_version=profile.prompt_version,
                provider=self._extractor.provider_name,
                model=self._extractor.model_name,
                status="failed",
                error=type(error).__name__,
            )
            logger.exception(
                "extraction_failed document_id=%s run_id=%s provider=%s model=%s profile=%s "
                "error_type=%s",
                document.id,
                failed_run.id,
                self._extractor.provider_name,
                self._extractor.model_name,
                profile.name,
                type(error).__name__,
            )
            if provider_extraction is not None:
                logger.error(
                    "extraction_failed_result document_id=%s run_id=%s concept_count=%s "
                    "entity_count=%s claim_count=%s relationship_count=%s",
                    document.id,
                    failed_run.id,
                    len(provider_extraction.result.concepts),
                    len(provider_extraction.result.entities),
                    len(provider_extraction.result.claims),
                    len(provider_extraction.result.relationships),
                )
            self._extraction_store.save(failed_run)
            raise ExtractionRunFailedError(failed_run.id) from error

        completed_run = new_extraction_run(
            document_id=document.id,
            profile_name=profile.name,
            schema_version=profile.schema_version,
            prompt_version=profile.prompt_version,
            provider=provider_extraction.provider,
            model=provider_extraction.model,
            status="completed",
            result=result,
            response_id=provider_extraction.response_id,
            usage=provider_extraction.usage,
        )
        self._extraction_store.save(completed_run)
        logger.info(
            "extraction_completed document_id=%s run_id=%s provider=%s model=%s profile=%s "
            "claim_count=%s",
            document.id, completed_run.id, completed_run.provider, completed_run.model,
            profile.name, len(result.claims),
        )
        return completed_run

    def get_document(self, document_id: UUID):
        """Expose the preserved source only to composed application use cases."""
        return self._document_store.get(document_id)

def resolve_evidence(content: str, result: ExtractionResult) -> ExtractionResult:
    """Locate evidence without trusting model offsets.

    Matching is literal except for Unicode canonical equivalence. The saved quote is always
    the exact slice from the original source, so whitespace and editorial changes still fail.
    """

    normalized_content = unicodedata.normalize("NFC", content)

    def original_offset(normalized_offset: int) -> int:
        for offset in range(len(content) + 1):
            if len(unicodedata.normalize("NFC", content[:offset])) == normalized_offset:
                return offset
        raise ExtractionEvidenceError("Evidence location could not be mapped to the source")

    def resolve(evidence: Evidence) -> Evidence:
        normalized_quote = unicodedata.normalize("NFC", evidence.quote)
        positions: list[int] = []
        start = normalized_content.find(normalized_quote)
        while start != -1:
            positions.append(start)
            start = normalized_content.find(normalized_quote, start + 1)

        if not positions:
            raise ExtractionEvidenceError("Evidence quote does not occur in the source document")
        if len(positions) > 1:
            raise ExtractionEvidenceError("Evidence quote is ambiguous in the source document")

        start_char = original_offset(positions[0])
        end_char = original_offset(positions[0] + len(normalized_quote))
        source_quote = content[start_char:end_char]
        return Evidence(
            quote=source_quote,
            start_char=start_char,
            end_char=end_char,
            start_line=content.count("\n", 0, start_char) + 1,
            end_line=content.count("\n", 0, end_char - 1) + 1,
        )

    def resolved_items(items: list[Concept] | list[Entity] | list[Claim] | list[Relationship]):
        return [
            item.model_copy(
                update={"evidence": [resolve(evidence) for evidence in item.evidence]}
            )
            for item in items
        ]

    return ExtractionResult(
        title=result.title,
        concepts=resolved_items(result.concepts),
        entities=resolved_items(result.entities),
        claims=resolved_items(result.claims),
        relationships=resolved_items(result.relationships),
    )


def validate_evidence(content: str, result: ExtractionResult) -> None:
    """Reject outputs whose evidence or relationship references are not source-grounded."""
    items = [*result.concepts, *result.entities, *result.claims]
    known_references = {
        ("concept", item.id) for item in result.concepts
    } | {("entity", item.id) for item in result.entities} | {
        ("claim", item.id) for item in result.claims
    }

    for item in [*items, *result.relationships]:
        for evidence in item.evidence:
            if evidence.start_char is None or evidence.end_char is None:
                raise ExtractionEvidenceError("Evidence location was not resolved")
            if evidence.end_char > len(content) or evidence.start_char >= evidence.end_char:
                raise ExtractionEvidenceError("Evidence range is outside the source document")
            if content[evidence.start_char : evidence.end_char] != evidence.quote:
                raise ExtractionEvidenceError("Evidence quote does not match the source document")

    for relationship in result.relationships:
        source = (relationship.source.kind, relationship.source.id)
        target = (relationship.target.kind, relationship.target.id)
        if source not in known_references or target not in known_references:
            raise ExtractionEvidenceError("Relationship references an unknown extracted item")
