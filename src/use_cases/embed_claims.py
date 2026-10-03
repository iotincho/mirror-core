"""Generate and persist versioned vectors for claims in one completed extraction."""

import hashlib
import logging

from src.domain.documents import Document
from src.embeddings.contracts import ClaimEmbeddingRecord, EmbeddingSpec
from src.services.claim_embedding_store import ClaimEmbeddingStore, ClaimEmbeddingStoreError
from src.services.embedding_provider import EmbeddingProvider, EmbeddingProviderError
from src.services.extraction_store import ExtractionRun

logger = logging.getLogger(__name__)


class ClaimEmbeddingFailedError(RuntimeError):
    """Signals that a completed extraction could not receive claim embeddings."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Extraction run {run_id} could not be embedded")


class EmbedClaims:
    """Embed claim text while retaining the extraction run that produced each claim."""

    def __init__(self, provider: EmbeddingProvider, store: ClaimEmbeddingStore) -> None:
        self._provider = provider
        self._store = store

    def execute(self, document: Document, extraction: ExtractionRun) -> int:
        if extraction.status != "completed" or extraction.result is None:
            raise ClaimEmbeddingFailedError(str(extraction.id))
        claims = extraction.result.claims
        if not claims:
            return 0

        stage = "provider"
        try:
            vectors = self._provider.embed([claim.text for claim in claims])
            if len(vectors) != len(claims):
                raise EmbeddingProviderError("Provider returned an unexpected number of embeddings")
            spec = vectors[0].spec
            if any(vector.spec != spec for vector in vectors):
                raise EmbeddingProviderError(
                    "Provider returned incompatible embedding specifications"
                )
            records = []
            for claim, vector in zip(claims, vectors, strict=True):
                record = self._record(
                    document, extraction, claim.id, claim.text, vector.vector, spec
                )
                graph_id = extraction.item_graph_ids.get(f"claim:{claim.id}")
                if graph_id:
                    record = record.model_copy(update={
                        "claim_graph_id": graph_id,
                        "id": f"{graph_id}:embedding:{spec.index_suffix}:{record.text_hash[:16]}",
                    })
                records.append(record)
            stage = "persistence"
            self._store.persist_claim_embeddings(records, spec)
        except (EmbeddingProviderError, ClaimEmbeddingStoreError) as error:
            logger.exception(
                "claim_embedding_failed document_id=%s run_id=%s stage=%s provider=%s "
                "model=%s dimensions=%s claim_count=%s",
                document.id, extraction.id, stage, self._provider.spec.provider,
                self._provider.spec.model, self._provider.spec.dimensions, len(claims),
            )
            raise ClaimEmbeddingFailedError(str(extraction.id)) from error
        return len(records)

    @staticmethod
    def _record(
        document: Document,
        extraction: ExtractionRun,
        claim_id: str,
        text: str,
        vector: list[float],
        spec: EmbeddingSpec,
    ) -> ClaimEmbeddingRecord:
        run_id = str(extraction.id)
        claim_graph_id = f"{run_id}:claim:{claim_id}"
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return ClaimEmbeddingRecord(
            id=f"{claim_graph_id}:embedding:{spec.index_suffix}:{text_hash[:16]}",
            claim_graph_id=claim_graph_id,
            claim_local_id=claim_id,
            document_id=str(document.id),
            run_id=run_id,
            profile_name=extraction.profile_name,
            prompt_version=extraction.prompt_version,
            text_hash=text_hash,
            vector=vector,
            spec=spec,
        )
