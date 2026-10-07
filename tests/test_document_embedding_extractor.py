"""Token limits, original-preserving segmentation, provider validation and replay."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.document_embeddings import (
    DocumentEmbeddingExtractor,
    EmbeddingConfiguration,
    Segmentation,
    bounded_spans,
    token_count,
)
from src.extractors.openai_document_embeddings import OpenAIDocumentEmbeddingProvider
from src.services.document_store import FileDocumentStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def layer(tmp_path, content="Hoy siento alegría.", **config):
    document = build_document(NewDocument(content=content))
    documents = FileDocumentStore(tmp_path / "documents")
    await documents.save(document)
    provider = SimpleNamespace(
        segment=AsyncMock(return_value=Segmentation(sections=[])),
        embed=AsyncMock(side_effect=lambda texts, config: [[1.0, 0.0, 0.0] for _ in texts]),
    )
    store = SimpleNamespace(existing=AsyncMock(return_value=None), persist=AsyncMock())
    extractor = DocumentEmbeddingExtractor(
        documents,
        LayerArtifacts(tmp_path / "layers"),
        store,
        EmbeddingConfiguration(segmentation_model="test", dimensions=3, **config),
        provider,
    )
    return document, extractor, provider, store


async def test_small_note_one_vector_dry_run_and_replay(tmp_path):
    document, extractor, provider, store = await layer(tmp_path)
    run = uuid4()
    output = await extractor.extract(document, run_id=run)
    assert output == await extractor.extract(document, run_id=run)
    provider.embed.assert_awaited_once()
    provider.segment.assert_not_awaited()
    store.persist.assert_not_awaited()
    assert output.payload["sections"][0]["text"] == document.content
    later = DocumentEmbeddingExtractor(
        extractor.documents, extractor.artifacts, store, extractor.configuration
    )
    await later.persist(output)
    store.persist.assert_awaited_once()


async def test_thematic_ranges_repaired_without_text_comparison(tmp_path):
    content = "Árbol 🌳. Una alegría enorme.\n" * 200
    document, extractor, provider, _ = await layer(
        tmp_path,
        content,
        segmentation_threshold=100,
        section_max_tokens=128,
        section_target_tokens=64,
        window_tokens=512,
    )
    provider.segment.return_value = Segmentation(
        sections=[
            {"start_block": 2, "end_block": 3},
            {"start_block": 3, "end_block": 4},
            {"start_block": -1, "end_block": 999},
        ]
    )
    output = await extractor.extract(document)
    sections = output.payload["sections"]
    assert len(sections) > 1
    assert "".join(section["text"] for section in sections) == content
    assert all(section["tokens"] <= 128 for section in sections)
    assert provider.segment.await_count > 1
    for call in provider.embed.await_args_list:
        assert all(token_count(text) <= 128 for text in call.args[0])


async def test_skip_complete_existing_and_force_regeneration(tmp_path):
    document, extractor, provider, store = await layer(tmp_path)
    output = await extractor.extract(document)
    store.existing.return_value = output
    provider.embed.reset_mock()
    await extractor.extract(document, dry_run=False)
    provider.embed.assert_not_awaited()
    extractor.force = True
    result = await extractor.extract(document)
    assert result.payload["force"] is True
    provider.embed.assert_awaited_once()


async def test_incompatible_existing_requires_force(tmp_path):
    document, extractor, _, store = await layer(tmp_path)
    output = await extractor.extract(document)
    store.existing.return_value = output
    extractor.configuration = extractor.configuration.model_copy(
        update={"section_max_tokens": 3000}
    )
    with pytest.raises(ValueError, match="requires_force"):
        await extractor.extract(document)


@pytest.mark.parametrize("vector", [[1, 0], [float("nan"), 0, 1], [0, 0, 0]])
async def test_invalid_vectors_never_become_artifacts(tmp_path, vector):
    document, extractor, provider, store = await layer(tmp_path)
    provider.embed.side_effect = None
    provider.embed.return_value = [vector]
    run = uuid4()
    with pytest.raises(ValueError, match="embedding_vector_invalid"):
        await extractor.extract(document, run_id=run, dry_run=False)
    assert await extractor.artifacts.get(document.id, run) is None
    store.persist.assert_not_awaited()


async def test_local_spans_preserve_unicode_and_token_limit():
    text = "🌳Árbol\n" * 100
    spans = list(bounded_spans(text, 32))
    assert "".join(text[start:end] for start, end in spans) == text
    assert all(token_count(text[start:end]) <= 32 for start, end in spans)


async def test_openai_adapter_checks_length_before_call_and_orders_vectors():
    client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    data=[
                        SimpleNamespace(index=1, embedding=[0, 1, 0]),
                        SimpleNamespace(index=0, embedding=[1, 0, 0]),
                    ]
                )
            )
        )
    )
    provider = OpenAIDocumentEmbeddingProvider(None, "test", client=client)
    config = EmbeddingConfiguration(segmentation_model="test", dimensions=3)
    assert await provider.embed(["hola", "mundo"], config) == [[1, 0, 0], [0, 1, 0]]
    with pytest.raises(ValueError, match="token_limit"):
        await provider.embed(["hola " * 10000], config)
    assert client.embeddings.create.await_count == 1
