"""Cross-document experiment: evidence, candidate isolation and dry-run behavior."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.constellation.contracts import LinkChoice, LinkChoices, LinkType
from src.constellation.link_documents import LinkDocuments
from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector, EvidenceReference, SimilarClaim
from src.extraction.contracts import Claim, ClaimType, Evidence, ExtractionResult
from src.services.extraction_store import new_extraction_run


class Embeddings:
    def embed(self, texts):
        spec = EmbeddingSpec(provider="fake", model="tiny", dimensions=2)
        return [EmbeddingVector(vector=[1.0, 0.0], spec=spec) for _ in texts]


class Search:
    def __init__(self, results):
        self.results = results

    def search_claim_embeddings(self, vector, spec, limit):
        return self.results


class Provider:
    def __init__(self, target_id, relation_type=LinkType.REVISITS):
        self.target_id = target_id
        self.relation_type = relation_type
        self.seen = []

    def compare(self, source, candidates, source_authored_at):
        self.seen.append(candidates)
        return LinkChoices(links=[LinkChoice(
            target_claim_id=self.target_id, relation_type=self.relation_type,
        )])


class Graph:
    def __init__(self):
        self.saved = []

    def persist_cross_document_links(self, links):
        self.saved.extend(links)


def run():
    document_id = uuid4()
    source = Claim(id="c1", text="Quiero volver a pintar", type=ClaimType.DESIRE,
                   evidence=[Evidence(quote="Quiero volver a pintar", start_char=0,
                                      end_char=22, start_line=1, end_line=1)])
    extraction = new_extraction_run(
        document_id=document_id, profile_name="v5", schema_version="v3",
        prompt_version="v5", provider="fake", model="fake", status="completed",
        result=ExtractionResult(concepts=[], entities=[], claims=[source], relationships=[]),
    )
    return extraction


def candidate(document_id, claim_id="other", profile="v5", evidence=True, authored_at=None):
    return SimilarClaim(
        claim_id=claim_id, claim_local_id="c2", document_id=str(document_id),
        run_id=str(uuid4()), profile_name=profile, prompt_version=profile,
        text="Otra vez quiero pintar", type="desire", score=0.79,
        evidence=[EvidenceReference(quote="Otra vez quiero pintar")] if evidence else [],
        document_authored_at=authored_at or datetime.now(UTC),
    )


def test_dry_run_links_only_cited_claims_from_other_documents():
    source = run()
    other = candidate(uuid4())
    provider, graph = Provider(other.claim_id), Graph()
    use_case = LinkDocuments(
        Embeddings(), Search([candidate(source.document_id),
                              candidate(uuid4(), profile="v4"), other]), provider, graph,
    )

    report = use_case.execute(source, source_authored_at=datetime(2026, 1, 1, tzinfo=UTC))

    assert report.compared_pairs == 1
    assert report.persisted is False
    assert len(report.links) == 1
    assert report.links[0].source_evidence[0].quote == "Quiero volver a pintar"
    assert report.links[0].target_evidence[0].quote == "Otra vez quiero pintar"
    assert graph.saved == []
    assert provider.seen[0] == [other]


def test_persist_is_explicit_and_rejects_unretrieved_ids():
    source = run()
    other = candidate(uuid4())
    graph = Graph()
    report = LinkDocuments(Embeddings(), Search([other]), Provider(other.claim_id), graph).execute(
        source, persist=True, source_authored_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert graph.saved == report.links

    with pytest.raises(ValueError, match="outside retrieved"):
        LinkDocuments(Embeddings(), Search([other]), Provider("invented"), Graph()).execute(
            source, source_authored_at=datetime(2026, 1, 1, tzinfo=UTC)
        )


def test_same_document_or_missing_evidence_never_reaches_comparator():
    source = run()
    provider = Provider("unused")
    report = LinkDocuments(
        Embeddings(), Search([candidate(source.document_id), candidate(uuid4(), evidence=False)]),
        provider, Graph(),
    ).execute(source)
    assert report.links == []
    assert provider.seen == []


def test_temporal_links_are_oriented_from_earlier_to_later_claim() -> None:
    source = run()
    previous = candidate(uuid4(), authored_at=datetime(2026, 1, 1, tzinfo=UTC))
    provider = Provider(previous.claim_id, LinkType.SHIFTS)

    report = LinkDocuments(Embeddings(), Search([previous]), provider, Graph()).execute(
        source, source_authored_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    assert report.links[0].source_claim_id == previous.claim_id
    assert report.links[0].target_claim_id.endswith(":claim:c1")
    assert report.links[0].source_document_id == previous.document_id


def test_symmetric_links_have_a_stable_canonical_orientation() -> None:
    source = run()
    other = candidate(uuid4(), claim_id="aaa")
    report = LinkDocuments(
        Embeddings(), Search([other]), Provider(other.claim_id, LinkType.SAME_REFERENT), Graph()
    ).execute(source)

    assert [report.links[0].source_claim_id, report.links[0].target_claim_id] == sorted(
        [f"{source.id}:claim:c1", "aaa"]
    )
