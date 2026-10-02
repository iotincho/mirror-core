"""Retrieve candidates and verify cross-document links without changing source runs."""

import logging
from datetime import datetime
from typing import Any, Protocol

from src.constellation.contracts import CrossDocumentLink, LinkReport, LinkType
from src.constellation.provider import LinkProvider
from src.constellation.supplement import prepare_supplement
from src.domain.documents import Document
from src.embeddings.contracts import (
    ClaimEmbeddingRecord,
    EmbeddingSpec,
    EvidenceReference,
    SimilarClaim,
)
from src.services.claim_embedding_store import ClaimEmbeddingStore
from src.services.embedding_provider import EmbeddingProvider
from src.services.extraction_store import ExtractionRun, FileExtractionStore
from src.use_cases.embed_claims import EmbedClaims

logger = logging.getLogger(__name__)


class LinkStore(Protocol):
    def existing_document_items(self, document_id: str) -> list[dict[str, Any]]: ...

    def persist_link_analysis(
        self, document: Document, supplement: ExtractionRun | None,
        links: list[CrossDocumentLink],
    ) -> None: ...

    def persist_claim_embeddings(
        self, records: list[ClaimEmbeddingRecord], spec: EmbeddingSpec,
    ) -> None: ...


class LinkDocuments:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        search: ClaimEmbeddingStore,
        provider: LinkProvider,
        graph: LinkStore,
        extraction_store: FileExtractionStore,
        *,
        provider_name: str = "openai",
        model_name: str = "unknown",
    ) -> None:
        self._embeddings = embeddings
        self._search = search
        self._provider = provider
        self._graph = graph
        self._extraction_store = extraction_store
        self._provider_name = provider_name
        self._model_name = model_name

    def execute(
        self,
        extraction: ExtractionRun,
        document: Document,
        *,
        persist: bool = False,
        candidates_per_claim: int = 5,
        max_claims: int = 20,
    ) -> LinkReport:
        if extraction.status != "completed" or extraction.result is None:
            raise ValueError("A completed extraction is required")
        if document.id != extraction.document_id:
            raise ValueError("Source document does not match extraction")
        if not 1 <= candidates_per_claim <= 10 or not 1 <= max_claims <= 50:
            raise ValueError("Candidate and claim limits are out of range")

        links: list[CrossDocumentLink] = []
        claims = extraction.result.claims[:max_claims]
        # Even an empty extraction can discover omissions in the complete original.
        texts = [claim.text for claim in claims] + [document.content]
        vectors = self._embeddings.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("Embedding provider returned an unexpected number of vectors")
        candidates: list[SimilarClaim] = []
        seen: set[tuple[str, str]] = set()
        for vector in vectors:
            found = self._search.search_claim_embeddings(
                vector.vector, vector.spec, min(50, candidates_per_claim * 4 + 4)
            )
            # Each user's workspace has a separate ArcadeDB database. Never cross that boundary.
            selected_count = 0
            for candidate in found:
                key = (candidate.document_id, candidate.text.casefold())
                if (
                    candidate.document_id == str(extraction.document_id)
                    or candidate.profile_name != extraction.profile_name
                    or not candidate.evidence
                    or key in seen
                ):
                    continue
                seen.add(key)
                candidates.append(candidate)
                selected_count += 1
                if selected_count == candidates_per_claim or len(candidates) == 50:
                    break
            if len(candidates) == 50:
                break
        analysis = self._provider.analyze(document, extraction, candidates)
        existing = self._graph.existing_document_items(str(document.id))
        supplement = prepare_supplement(
            document, extraction, analysis.additions, existing,
            provider=self._provider_name, model=self._model_name,
        )
        if supplement is not None:
            try:
                # Repeated identical analyses reuse their immutable audit record.
                supplement = self._extraction_store.get(document.id, supplement.id)
            except FileNotFoundError:
                pass
        source_claims = {
            extraction.item_graph_ids.get(f"claim:{claim.id}", f"{extraction.id}:claim:{claim.id}"):
            claim for claim in extraction.result.claims
        }
        source_aliases = {}
        if supplement is not None and supplement.result is not None:
            for claim in supplement.result.claims:
                graph_id = supplement.item_graph_ids[f"claim:{claim.id}"]
                if claim.id in source_claims:
                    raise ValueError("Supplemental ID collides with an existing source graph ID")
                source_aliases[claim.id] = graph_id
                source_claims[graph_id] = claim
        allowed = {candidate.claim_id: candidate for candidate in candidates}
        for choice in analysis.links:
            candidate = allowed.get(choice.target_claim_id)
            if candidate is None:
                raise ValueError("Link provider referenced a claim outside retrieved candidates")
            source_id = source_aliases.get(choice.source_claim_id, choice.source_claim_id)
            claim = source_claims.get(source_id)
            if claim is None:
                raise ValueError("Link provider referenced an unknown source claim")
            source_evidence = [
                EvidenceReference(
                    quote=item.quote,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in claim.evidence
            ]
            link = self._build_link(
                source_graph_id=source_id, extraction_document_id=str(document.id),
                source_evidence=source_evidence, source_authored_at=document.authored_at,
                candidate=candidate, relation_type=choice.relation_type,
            )
            if link is not None and link not in links:
                links.append(link)
        warnings = []
        embeddings_status = "not_required"
        if persist:
            if supplement is not None:
                # Stage audit metadata before the graph transaction. A staged run is
                # not graph-ready and cannot be used as a full initial extraction.
                self._extraction_store.save(supplement)
            self._graph.persist_link_analysis(document, supplement, links)
            if supplement is not None and supplement.result and supplement.result.claims:
                try:
                    EmbedClaims(self._embeddings, self._graph).execute(document, supplement)
                    embeddings_status = "ready"
                except Exception as error:
                    logger.warning(
                        "supplement_embeddings_pending document_id=%s run_id=%s error_type=%s",
                        document.id, supplement.id, type(error).__name__,
                    )
                    embeddings_status = "pending"
                    warnings.append(
                        "Los elementos y vínculos se guardaron, pero sus embeddings "
                        "quedaron pendientes. Podés reintentarlos sin repetir el análisis."
                    )
        elif supplement is not None and supplement.result and supplement.result.claims:
            embeddings_status = "not_persisted"
        return LinkReport(
            document_id=str(extraction.document_id),
            run_id=str(extraction.id),
            compared_pairs=len(candidates),
            persisted=persist,
            links=links,
            profile="link-v2", supplemental_extraction=supplement,
            embeddings_status=embeddings_status, warnings=warnings,
        )

    @staticmethod
    def _build_link(
        *,
        source_graph_id: str,
        extraction_document_id: str,
        source_evidence: list[EvidenceReference],
        source_authored_at: datetime | None,
        candidate: SimilarClaim,
        relation_type: LinkType,
    ) -> CrossDocumentLink | None:
        """Return a stable orientation without turning symmetric links into timelines."""
        link = CrossDocumentLink(
            source_claim_id=source_graph_id,
            target_claim_id=candidate.claim_id,
            source_document_id=extraction_document_id,
            target_document_id=candidate.document_id,
            relation_type=relation_type,
            source_evidence=source_evidence,
            target_evidence=candidate.evidence,
            similarity=candidate.score,
            profile="link-v2",
        )

        if relation_type in {LinkType.SHIFTS, LinkType.REVISITS}:
            target_authored_at = candidate.document_authored_at
            if (
                source_authored_at is None
                or target_authored_at is None
                or source_authored_at == target_authored_at
            ):
                return None
            # The conceptual link always advances from its antecedent to its later expression.
            if source_authored_at > target_authored_at:
                return LinkDocuments._reverse(link)
            return link

        # Same referent and tension are symmetric. A canonical representation makes
        # retries from either document idempotent without inventing a temporal order.
        if link.source_claim_id > link.target_claim_id:
            return LinkDocuments._reverse(link)
        return link

    @staticmethod
    def _reverse(link: CrossDocumentLink) -> CrossDocumentLink:
        return link.model_copy(
            update={
                "source_claim_id": link.target_claim_id,
                "target_claim_id": link.source_claim_id,
                "source_document_id": link.target_document_id,
                "target_document_id": link.source_document_id,
                "source_evidence": link.target_evidence,
                "target_evidence": link.source_evidence,
            }
        )
