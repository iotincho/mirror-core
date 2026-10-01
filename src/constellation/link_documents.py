"""Retrieve candidates and verify cross-document links without changing source runs."""

from datetime import datetime
from typing import Protocol

from src.constellation.contracts import CrossDocumentLink, LinkReport, LinkType
from src.constellation.provider import LinkProvider
from src.embeddings.contracts import EvidenceReference, SimilarClaim
from src.services.claim_embedding_store import ClaimEmbeddingStore
from src.services.embedding_provider import EmbeddingProvider
from src.services.extraction_store import ExtractionRun


class LinkStore(Protocol):
    def persist_cross_document_links(self, links: list[CrossDocumentLink]) -> None: ...


class LinkDocuments:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        search: ClaimEmbeddingStore,
        provider: LinkProvider,
        graph: LinkStore,
    ) -> None:
        self._embeddings = embeddings
        self._search = search
        self._provider = provider
        self._graph = graph

    def execute(
        self,
        extraction: ExtractionRun,
        *,
        persist: bool = False,
        candidates_per_claim: int = 5,
        max_claims: int = 20,
        source_authored_at: datetime | None = None,
    ) -> LinkReport:
        if extraction.status != "completed" or extraction.result is None:
            raise ValueError("A completed extraction is required")
        if not 1 <= candidates_per_claim <= 10 or not 1 <= max_claims <= 50:
            raise ValueError("Candidate and claim limits are out of range")

        links: list[CrossDocumentLink] = []
        compared_pairs = 0
        claims = extraction.result.claims[:max_claims]
        vectors = self._embeddings.embed([claim.text for claim in claims]) if claims else []
        if len(vectors) != len(claims):
            raise ValueError("Embedding provider returned an unexpected number of vectors")
        for claim, vector in zip(claims, vectors, strict=True):
            found = self._search.search_claim_embeddings(
                vector.vector, vector.spec, min(50, candidates_per_claim * 4 + 4)
            )
            # Each user's workspace has a separate ArcadeDB database. Never cross that boundary.
            candidates: list[SimilarClaim] = []
            seen: set[tuple[str, str]] = set()
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
                if len(candidates) == candidates_per_claim:
                    break
            if not candidates:
                continue
            compared_pairs += len(candidates)
            allowed = {candidate.claim_id: candidate for candidate in candidates}
            source_evidence = [
                EvidenceReference(
                    quote=item.quote,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in claim.evidence
            ]
            if not source_evidence:
                continue
            choices = self._provider.compare(claim, candidates, source_authored_at)
            for choice in choices.links:
                candidate = allowed.get(choice.target_claim_id)
                if candidate is None:
                    raise ValueError(
                        "Link provider referenced a claim outside retrieved candidates"
                    )
                if choice.relation_type == LinkType.SHIFTS and (
                    source_authored_at is None or candidate.document_authored_at is None
                ):
                    continue
                link = CrossDocumentLink(
                    source_claim_id=f"{extraction.id}:claim:{claim.id}",
                    target_claim_id=candidate.claim_id,
                    source_document_id=str(extraction.document_id),
                    target_document_id=candidate.document_id,
                    relation_type=choice.relation_type,
                    source_evidence=source_evidence,
                    target_evidence=candidate.evidence,
                    similarity=candidate.score,
                )
                if link not in links:
                    links.append(link)
        if persist and links:
            self._graph.persist_cross_document_links(links)
        return LinkReport(
            document_id=str(extraction.document_id),
            run_id=str(extraction.id),
            compared_pairs=compared_pairs,
            persisted=persist,
            links=links,
        )
