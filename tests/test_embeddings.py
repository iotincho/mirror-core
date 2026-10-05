from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.documents import Document
from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector, SimilarClaim, SimilarDocument
from src.extraction.contracts import Claim, ClaimType, Evidence, ExtractionResult
from src.services.extraction_store import new_extraction_run
from src.services.openai_embedding_provider import OpenAIEmbeddingProvider
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.embed_documents import EmbedDocument
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument
from src.use_cases.search_semantically import SearchSemantically
from src.use_cases.search_similar_claims import SearchSimilarClaims


class FakeEmbeddingProvider:
    spec = EmbeddingSpec(provider="fake", model="fake-embedding", dimensions=3)

    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        self.inputs.append(texts)
        return [EmbeddingVector(vector=[0.1, 0.2, 0.3], spec=self.spec) for _ in texts]


class FakeDocumentEmbeddingStore:
    def __init__(self) -> None:
        self.record = None
        self.spec = None
        self.results: list[SimilarDocument] = []

    async def persist_document_embedding(self, record, spec) -> None:
        self.record = record
        self.spec = spec

    async def search_document_embeddings(self, vector, spec, limit):
        assert vector == [0.1, 0.2, 0.3]
        assert spec == FakeEmbeddingProvider.spec
        assert limit == 3
        return self.results


class FakeClaimEmbeddingStore:
    def __init__(self) -> None:
        self.records = []
        self.spec = None
        self.results: list[SimilarClaim] = []

    async def persist_claim_embeddings(self, records, spec) -> None:
        self.records.extend(records)
        self.spec = spec

    async def search_claim_embeddings(self, vector, spec, limit):
        assert vector == [0.1, 0.2, 0.3]
        assert spec == FakeEmbeddingProvider.spec
        assert limit == 3
        return self.results


def completed_extraction(document: Document):
    evidence = Evidence(
        quote="Quiero más autonomía.",
        start_char=0,
        end_char=21,
        start_line=1,
        end_line=1,
    )
    return new_extraction_run(
        document_id=document.id,
        profile_name="v3",
        schema_version="v2",
        prompt_version="v3",
        provider="openai",
        model="gpt-5.6-luna",
        status="completed",
        result=ExtractionResult(
            concepts=[],
            entities=[],
            claims=[
                Claim(
                    id="claim_autonomy",
                    text="Quiero más autonomía.",
                    type=ClaimType.DESIRE,
                    evidence=[evidence],
                )
            ],
            relationships=[],
        ),
    )


@pytest.mark.anyio
async def test_embed_claims_persists_versioned_claim_vectors() -> None:
    document = Document(
        id=uuid4(),
        content="Quiero más autonomía.",
        source="test",
        metadata={},
        created_at=datetime.now(UTC),
    )
    provider = FakeEmbeddingProvider()
    store = FakeClaimEmbeddingStore()

    count = await EmbedClaims(provider, store).execute(document, completed_extraction(document))

    assert count == 1
    assert provider.inputs == [["Quiero más autonomía."]]
    record = store.records[0]
    assert record.document_id == str(document.id)
    assert record.profile_name == "v3"
    assert record.prompt_version == "v3"
    assert record.claim_graph_id.endswith(":claim:claim_autonomy")
    assert store.spec == provider.spec


@pytest.mark.anyio
async def test_search_similar_claims_returns_claims_with_evidence() -> None:
    provider = FakeEmbeddingProvider()
    store = FakeClaimEmbeddingStore()
    store.results = [
        SimilarClaim(
            claim_id="run:claim:claim_autonomy",
            claim_local_id="claim_autonomy",
            document_id="document",
            run_id="run",
            profile_name="v3",
            prompt_version="v3",
            text="Quiero más autonomía.",
            type="desire",
            score=0.91,
            evidence=[],
        )
    ]

    result = await SearchSimilarClaims(provider, store).execute("libertad en el trabajo", limit=3)

    assert result == store.results
    assert provider.inputs == [["libertad en el trabajo"]]


@pytest.mark.anyio
async def test_processing_flow_embeds_claims_after_graph_persistence() -> None:
    document = Document(
        id=uuid4(),
        content="Quiero más autonomía.",
        source="test",
        metadata={},
        created_at=datetime.now(UTC),
    )
    extraction = completed_extraction(document)
    provider = FakeEmbeddingProvider()
    store = FakeClaimEmbeddingStore()
    document_store = FakeDocumentEmbeddingStore()

    class FakeExtractAndPersist:
        async def execute(self, document_id, profile_name="v4"):
            assert document_id == document.id
            assert profile_name == "v4"
            return extraction

        async def get_document(self, document_id):
            assert document_id == document.id
            return document

    result = await ExtractPersistAndEmbedDocument(
        FakeExtractAndPersist(),
        EmbedClaims(provider, store),
        EmbedDocument(provider, document_store),
    ).execute(document.id)

    assert result == extraction
    assert len(store.records) == 1
    assert document_store.record.document_id == str(document.id)


@pytest.mark.anyio
async def test_openai_embedding_provider_uses_configured_vector_contract() -> None:
    captured = {}

    class FakeEmbeddings:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="text-embedding-3-small",
                data=[
                    SimpleNamespace(index=1, embedding=[0.3, 0.4]),
                    SimpleNamespace(index=0, embedding=[0.1, 0.2]),
                ],
                usage=SimpleNamespace(prompt_tokens=7),
            )

    provider = OpenAIEmbeddingProvider(
        api_key="unused-in-test",
        model="text-embedding-3-small",
        dimensions=2,
        client=SimpleNamespace(embeddings=FakeEmbeddings()),
    )

    result = await provider.embed(["primer claim", "segundo claim"])

    assert captured == {
        "model": "text-embedding-3-small",
        "input": ["primer claim", "segundo claim"],
        "dimensions": 2,
        "encoding_format": "float",
    }
    assert [item.vector for item in result] == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.anyio
async def test_embed_document_persists_original_content_vector() -> None:
    document = Document(
        id=uuid4(),
        content="Quiero más autonomía.",
        source="test",
        metadata={"filename": "note.md"},
        created_at=datetime.now(UTC),
    )
    provider = FakeEmbeddingProvider()
    store = FakeDocumentEmbeddingStore()

    await EmbedDocument(provider, store).execute(document)

    assert provider.inputs == [[document.content]]
    assert store.record.document_id == str(document.id)
    assert store.record.content == document.content
    assert store.record.metadata == {"filename": "note.md"}
    assert store.spec == provider.spec


@pytest.mark.anyio
async def test_semantic_search_returns_score_ordered_documents_and_claims() -> None:
    provider = FakeEmbeddingProvider()
    claim_store = FakeClaimEmbeddingStore()
    document_store = FakeDocumentEmbeddingStore()
    claim_store.results = [
        SimilarClaim(
            claim_id="run:claim:claim_autonomy",
            claim_local_id="claim_autonomy",
            document_id="document",
            run_id="run",
            profile_name="v3",
            prompt_version="v3",
            text="Quiero más autonomía.",
            type="desire",
            score=0.8,
            evidence=[],
        )
    ]
    document_store.results = [
        SimilarDocument(
            document_id="document",
            content="Quiero más autonomía.",
            source="test",
            metadata={},
            created_at=datetime.now(UTC),
            score=0.9,
        )
    ]

    result = await SearchSemantically(provider, claim_store, document_store).execute(
        "libertad en el trabajo", limit=3
    )

    assert [item.target for item in result] == ["document", "claim"]
    assert provider.inputs == [["libertad en el trabajo"]]
