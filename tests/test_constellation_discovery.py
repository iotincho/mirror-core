"""Source context, proposal validation, audit and supplemental embedding retries."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.api.routes.constellation import router
from src.constellation.contracts import (
    DiscoveryLink,
    DocumentLinkAnalysis,
    LinkType,
    SupplementalItems,
)
from src.constellation.link_documents import LinkDocuments
from src.constellation.provider import OpenAILinkProvider
from src.constellation.supplement import prepare_supplement
from src.dependencies import get_embedding_provider
from src.domain.documents import Document
from src.extraction.contracts import (
    Claim,
    ClaimType,
    Entity,
    Evidence,
    ExtractionReference,
    ExtractionResult,
    Relationship,
    RelationshipType,
)
from src.extraction.profiles import V5_PROFILE
from src.services.document_store import FileDocumentStore
from src.services.embedding_provider import EmbeddingProviderError
from src.services.extraction_store import FileExtractionStore
from src.use_cases.extract_document import ExtractionEvidenceError
from src.workspaces.dependencies import get_workspace_runtime
from tests.test_constellation_links import Embeddings, Graph, Search, candidate, run

CONTENT = ("Quiero volver a pintar. El viernes descansé. "
           "Fue una buena forma de cerrar el viernes.")


def additions(quote="Fue una buena forma de cerrar el viernes."):
    return SupplementalItems(
        concepts=[], entities=[Entity(id="friday", name="viernes", type="día",
                                      evidence=[Evidence(quote=quote)])],
        claims=[Claim(id="rest", text="El viernes descansé.", type=ClaimType.OBSERVATION,
                      evidence=[Evidence(quote="El viernes descansé.")])], relationships=[],
    )


class DiscoveryProvider:
    def __init__(self, result):
        self.result = result
        self.received = None

    def analyze(self, document, extraction, candidates):
        self.received = document
        return self.result


class DiscoveryGraph(Graph):
    def __init__(self):
        super().__init__()
        self.supplements = []
        self.vectors = []

    def persist_link_analysis(self, document, supplement, links):
        super().persist_link_analysis(document, supplement, links)
        self.supplements.append(supplement)

    def persist_claim_embeddings(self, records, spec):
        self.vectors.extend(records)

    def supplemental_items_persisted(self, run):
        return any(supplement and supplement.id == run.id for supplement in self.supplements)

    def ready_extraction_ids(self, expected, spec):
        return set()


def setup_case(tmp_path, proposals=None):
    parent = run()
    document = Document(id=parent.document_id, content=CONTENT, source="test", metadata={},
                        created_at=datetime.now(UTC), authored_at=datetime(2026, 1, 1, tzinfo=UTC))
    other = candidate(uuid4())
    provider = DiscoveryProvider(DocumentLinkAnalysis(
        additions=proposals or additions(),
        links=[DiscoveryLink(source_claim_id="rest", target_claim_id=other.claim_id,
                             relation_type=LinkType.REVISITS)],
    ))
    graph, history = DiscoveryGraph(), FileExtractionStore(tmp_path)
    use_case = LinkDocuments(Embeddings(), Search([other]), provider, graph, history)
    return use_case, document, parent, provider, graph, history


def test_full_source_and_new_claim_links_are_returned_without_writes(tmp_path):
    use_case, document, parent, provider, graph, history = setup_case(tmp_path)
    report = use_case.execute(parent, document)
    assert provider.received.content == CONTENT
    assert report.supplemental_extraction.origin == "constellation"
    assert report.supplemental_extraction.parent_run_id == parent.id
    assert report.supplemental_extraction.result.entities[0].evidence[0].start_char is not None
    assert (report.links[0].source_claim_id
            == report.supplemental_extraction.item_graph_ids["claim:rest"])
    assert report.embeddings_status == "not_persisted"
    assert history.list_for_document(document.id) == []
    assert graph.saved == graph.supplements == graph.vectors == []


def test_persistence_records_provenance_and_uses_resolved_graph_id_for_vectors(tmp_path):
    use_case, document, parent, _, graph, history = setup_case(tmp_path)
    report = use_case.execute(parent, document, persist=True)
    assert report.persisted and report.embeddings_status == "ready"
    assert graph.saved == report.links
    assert graph.vectors[0].claim_graph_id == report.links[0].source_claim_id
    assert history.get(document.id, report.supplemental_extraction.id).parent_run_id == parent.id


def test_repeated_words_require_context_and_reject_before_any_write(tmp_path):
    use_case, document, parent, _, graph, history = setup_case(tmp_path, additions("viernes"))
    with pytest.raises(ExtractionEvidenceError, match="ambiguous"):
        use_case.execute(parent, document, persist=True)
    assert graph.saved == [] and history.list_for_document(document.id) == []
    assert "extend the contiguous quote" in V5_PROFILE.instructions
    assert "omit that item AND any relationship" in V5_PROFILE.instructions
    assert V5_PROFILE.prompt_version == "v5.1-title-v1"


def test_missing_or_invented_source_evidence_is_rejected(tmp_path):
    use_case, document, parent, provider, graph, _ = setup_case(tmp_path)
    provider.result = provider.result.model_copy(update={
        "additions": additions("Una frase de otro documento"),
    })
    with pytest.raises(ExtractionEvidenceError, match="does not occur"):
        use_case.execute(parent, document, persist=True)
    assert not graph.saved


def test_new_claim_cannot_invent_text_even_with_a_real_quote(tmp_path):
    use_case, document, parent, provider, graph, _ = setup_case(tmp_path)
    proposal = additions().model_copy(update={"claims": [
        additions().claims[0].model_copy(update={"text": "El autor evita trabajar los viernes."})
    ]})
    provider.result = provider.result.model_copy(update={"additions": proposal})
    with pytest.raises(ValueError, match="author's words"):
        use_case.execute(parent, document, persist=True)
    assert not graph.saved


def test_dangling_internal_reference_is_rejected_before_persistence(tmp_path):
    use_case, document, parent, provider, graph, history = setup_case(tmp_path)
    relation = Relationship(
        source=ExtractionReference(kind="claim", id="rest"), type=RelationshipType.ABOUT,
        target=ExtractionReference(kind="entity", id="unknown"),
        evidence=[Evidence(quote="El viernes descansé.")],
    )
    provider.result = provider.result.model_copy(update={
        "additions": additions().model_copy(update={"relationships": [relation]})
    })
    with pytest.raises(ExtractionEvidenceError, match="unknown extracted item"):
        use_case.execute(parent, document, persist=True)
    assert not graph.saved and not history.list_for_document(document.id)


def test_unknown_source_claim_is_rejected_before_persistence(tmp_path):
    use_case, document, parent, provider, graph, history = setup_case(tmp_path)
    provider.result = provider.result.model_copy(update={"links": [
        provider.result.links[0].model_copy(update={"source_claim_id": "invented-source"})
    ]})
    with pytest.raises(ValueError, match="unknown source claim"):
        use_case.execute(parent, document, persist=True)
    assert not graph.saved and not history.list_for_document(document.id)


def test_embedding_failure_preserves_successful_save_and_reports_pending(tmp_path):
    use_case, document, parent, _, graph, history = setup_case(tmp_path)

    class FailAfterRetrieval(Embeddings):
        def __init__(self):
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.calls > 1:
                raise EmbeddingProviderError("test unavailable")
            return super().embed(texts)

    use_case._embeddings = FailAfterRetrieval()
    report = use_case.execute(parent, document, persist=True)
    assert report.persisted and report.embeddings_status == "pending"
    assert report.warnings and graph.saved == report.links
    assert history.get(document.id, report.supplemental_extraction.id)


def test_identity_reuses_existing_items_but_not_another_claim_type():
    parent = run()
    document = Document(id=parent.document_id, content=CONTENT, source="test", metadata={},
                        created_at=datetime.now(UTC))
    existing = [
        {"id": "existing-friday", "kind": "entity", "name": "Viernes", "type": "día"},
        {"id": "existing-rest", "kind": "claim", "text": "El viernes descansé.",
         "type": "observation"},
    ]
    proposal = prepare_supplement(document, parent, additions(), existing,
                                  provider="test", model="test")
    assert proposal.item_graph_ids == {"entity:friday": "existing-friday",
                                       "claim:rest": "existing-rest"}
    assert set(proposal.reused_item_keys) == {"entity:friday", "claim:rest"}
    different = additions().model_copy(update={"claims": [
        additions().claims[0].model_copy(update={"type": ClaimType.BELIEF})
    ]})
    proposal = prepare_supplement(document, parent, different, existing,
                                  provider="test", model="test")
    assert proposal.item_graph_ids["claim:rest"] != "existing-rest"


def test_provider_payload_contains_the_entire_source_and_allows_discovery_without_candidates():
    parent = run()
    document = Document(id=parent.document_id, content=CONTENT, source="test", metadata={},
                        created_at=datetime.now(UTC))
    captured = []

    def parse(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output_parsed=DocumentLinkAnalysis(additions=additions(), links=[]))

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = OpenAILinkProvider(None, "test", client).analyze(document, parent, [])
    payload = json.loads(captured[0]["input"][1]["content"])
    assert payload["source"]["content"] == CONTENT
    assert payload["source"]["document_id"] == str(document.id)
    assert payload["source"]["claims"][0]["id"] == f"{parent.id}:claim:c1"
    assert result.additions.entities[0].name == "viernes"


def test_empty_parent_extraction_still_discovers_source_items(tmp_path):
    use_case, document, parent, provider, graph, _ = setup_case(tmp_path)
    empty = parent.model_copy(update={"result": ExtractionResult(
        concepts=[], entities=[], claims=[], relationships=[],
    )})
    provider.result = provider.result.model_copy(update={"links": []})
    report = use_case.execute(empty, document, persist=True)
    assert report.links == [] and report.supplemental_extraction.result.claims
    assert graph.supplements


@pytest.mark.anyio
async def test_retry_endpoint_requires_own_persisted_supplement(tmp_path):
    use_case, document, parent, _, graph, history = setup_case(tmp_path / "extractions")
    documents = FileDocumentStore(tmp_path / "documents")
    documents.save(document)
    report = use_case.execute(parent, document)
    supplement = report.supplemental_extraction
    history.save(supplement)
    history.save(parent)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_runtime] = lambda: SimpleNamespace(
        document_store=documents, extraction_store=history, graph_store=graph,
    )
    app.dependency_overrides[get_embedding_provider] = lambda: Embeddings()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        path = f"/documents/{document.id}/extractions/{supplement.id}/embeddings"
        assert (await client.post(path)).status_code == 409  # staged, not committed
        assert (await client.post(path.replace(str(document.id), str(uuid4())))).status_code == 404
        parent_path = path.replace(str(supplement.id), str(parent.id))
        assert (await client.post(parent_path)).status_code == 422
        graph.persist_link_analysis(document, supplement, report.links)
        response = await client.post(path)
        assert response.status_code == 200 and response.json()["claim_count"] == 1
        assert graph.vectors[0].claim_graph_id == supplement.item_graph_ids["claim:rest"]
        history_response = await client.get(f"/documents/{document.id}/extractions")
        assert history_response.status_code == 200
        record = next(item for item in history_response.json() if item["id"] == str(supplement.id))
        assert record["origin"] == "constellation" and record["graph_persisted"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
