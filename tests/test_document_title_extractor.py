"""Durable title generation and attribute-only persistence, without a live provider."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.adapters.providers.openai.document_title import DocumentTitleProviderError
from src.adapters.storage.arcadedb.document_titles import ArcadeDBDocumentTitleStore
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap.documents import build_title_provider as OpenAIDocumentTitleProvider
from src.core.documents.ports import DocumentNotFoundError
from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.contracts import ProviderMetadata
from src.core.extractors.document_title import TITLE_PROFILE, DocumentTitle
from src.use_cases.extraction.document_title import DocumentTitleExtractor

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def layer(tmp_path):
    document = build_document(
        NewDocument(content="Hoy aprendí a poner límites en el trabajo.", metadata={"a": "b"})
    )
    documents = FileDocumentStore(tmp_path / "documents")
    await documents.save(document)
    provider = SimpleNamespace(
        provider_name="fake",
        model_name="test",
        extract=AsyncMock(
            return_value=(
                DocumentTitle(title="Aprender a poner límites"),
                ProviderMetadata(provider="fake", model="test"),
            )
        ),
    )
    store = SimpleNamespace(update_title=AsyncMock())
    artifacts = LayerArtifacts(tmp_path / "layers")
    extractor = DocumentTitleExtractor(documents, artifacts, store, provider)
    return SimpleNamespace(
        document=document,
        documents=documents,
        provider=provider,
        store=store,
        artifacts=artifacts,
        extractor=extractor,
    )


async def test_dry_run_then_persist_and_replay_preserves_original(layer):
    run_id = uuid4()
    output = await layer.extractor.extract(layer.document, run_id=run_id)
    assert await layer.documents.get(layer.document.id) == layer.document
    layer.store.update_title.assert_not_called()
    assert output.payload == {"title": "Aprender a poner límites"}
    assert output.profile == TITLE_PROFILE
    assert output.request_config == {"provider": "fake", "model": "test"}
    assert await layer.extractor.extract(layer.document, run_id=run_id) == output
    later = DocumentTitleExtractor(layer.documents, layer.artifacts, layer.store)
    await later.persist(output)
    await later.persist(output)
    current = await layer.documents.get(layer.document.id)
    assert current.title == output.payload["title"]
    assert current.model_dump(exclude={"title"}) == layer.document.model_dump(exclude={"title"})
    assert layer.provider.extract.await_count == 1
    assert layer.store.update_title.call_args.args == (current,)


async def test_graph_failure_keeps_canonical_title_and_retries_without_provider(layer):
    output = await layer.extractor.extract(layer.document)
    layer.store.update_title.side_effect = ConnectionError("graph unavailable")
    with pytest.raises(ConnectionError):
        await layer.extractor.persist(output)
    assert (await layer.documents.get(layer.document.id)).title == output.payload["title"]
    layer.store.update_title.side_effect = None
    await DocumentTitleExtractor(layer.documents, layer.artifacts, layer.store).persist(output)
    assert layer.provider.extract.await_count == 1


async def test_file_failure_does_not_project_and_reuses_saved_generation(layer, monkeypatch):
    output = await layer.extractor.extract(layer.document)
    original = layer.documents.update_title
    monkeypatch.setattr(layer.documents, "update_title", AsyncMock(side_effect=OSError("disk")))
    with pytest.raises(OSError):
        await layer.extractor.persist(output)
    layer.store.update_title.assert_not_called()
    monkeypatch.setattr(layer.documents, "update_title", original)
    await layer.extractor.persist(output)
    assert layer.provider.extract.await_count == 1


async def test_interrupted_file_replacement_preserves_original_and_cleans_temporary(
    layer, monkeypatch
):
    output = await layer.extractor.extract(layer.document)

    def unavailable(*args):
        raise OSError("replacement unavailable")

    monkeypatch.setattr(Path, "replace", unavailable)
    with pytest.raises(OSError):
        await layer.extractor.persist(output)
    assert await layer.documents.get(layer.document.id) == layer.document
    assert not list(layer.documents._directory.glob("*.tmp"))
    layer.store.update_title.assert_not_called()


@pytest.mark.parametrize("title", ["Título importado", '  "Título original"  '])
async def test_existing_titles_are_preserved_even_with_stale_input_and_no_provider(layer, title):
    await layer.documents.update_title(layer.document.id, title)
    extractor = DocumentTitleExtractor(layer.documents, layer.artifacts, layer.store)
    result = await extractor.extract(layer.document, dry_run=False)
    assert result.payload == {"title": title} and result.provider is None
    assert (await layer.documents.get(layer.document.id)).title == title
    layer.provider.extract.assert_not_called()


async def test_existing_title_does_not_require_provider_credentials(layer):
    await layer.documents.update_title(layer.document.id, "Título importado")
    provider = OpenAIDocumentTitleProvider(None, None)
    extractor = DocumentTitleExtractor(layer.documents, layer.artifacts, layer.store, provider)
    result = await extractor.extract(layer.document, dry_run=False)
    assert result.payload == {"title": "Título importado"} and result.provider is None
    await provider.close()


async def test_late_result_does_not_overwrite_a_title_assigned_since_generation(layer):
    output = await layer.extractor.extract(layer.document)
    await layer.documents.update_title(layer.document.id, "Mi título elegido")
    await layer.extractor.persist(output)
    assert layer.store.update_title.call_args.args[0].title == "Mi título elegido"


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        "x" * 81,
        "Dos\nlíneas",
        " Espacio",
        "Dos  espacios",
        '"Comillas"',
        "`Markdown`",
        "Control\x00",
        "Dos\u2028líneas",
    ],
)
async def test_rejects_invalid_generated_titles_without_writing(layer, title):
    layer.provider.extract.return_value = (DocumentTitle.model_construct(title=title), None)
    with pytest.raises((ValidationError, ValueError)):
        await layer.extractor.extract(layer.document)
    assert await layer.documents.get(layer.document.id) == layer.document
    layer.store.update_title.assert_not_called()


async def test_missing_changed_and_foreign_originals_cannot_be_updated(layer, tmp_path):
    output = await layer.extractor.extract(layer.document)
    foreign = DocumentTitleExtractor(
        layer.documents, LayerArtifacts(tmp_path / "foreign-workspace"), layer.store
    )
    with pytest.raises(ValueError, match="not_saved_or_changed"):
        await foreign.persist(output)
    modified = output.model_copy(update={"payload": {"title": "Otro"}})
    with pytest.raises(ValueError, match="not_saved_or_changed"):
        await layer.extractor.persist(modified)
    changed = layer.document.model_copy(update={"content": "Otro original"})
    path = layer.documents._directory / f"{changed.id}.json"
    path.write_text(changed.model_dump_json())
    with pytest.raises(ValueError, match="source_changed"):
        await layer.extractor.persist(output)
    await layer.documents.delete(changed.id)
    with pytest.raises(DocumentNotFoundError):
        await layer.extractor.persist(output)
    assert not path.exists()
    layer.store.update_title.assert_not_called()


async def test_openai_uses_full_text_own_schema_and_safe_refusal(layer):
    response = SimpleNamespace(
        output_parsed=DocumentTitle(title="Aprender a poner límites"),
        id="response-1",
        model="resolved-model",
        usage=SimpleNamespace(input_tokens=100, output_tokens=10),
    )
    parse = AsyncMock(return_value=response)
    provider = OpenAIDocumentTitleProvider(
        "unused", "accepted-model", SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    result, metadata = await provider.extract(layer.document, TITLE_PROFILE)
    request = parse.call_args.kwargs
    assert request["input"][1]["content"] == layer.document.content
    assert request["input"][0]["content"] == TITLE_PROFILE.instructions
    assert request["text_format"] is DocumentTitle and request["store"] is False
    assert request["model"] == "accepted-model"
    assert metadata.model == "resolved-model" and metadata.input_tokens == 100
    assert result.title == "Aprender a poner límites"
    response.output_parsed = None
    with pytest.raises(DocumentTitleProviderError, match="structured title"):
        await provider.extract(layer.document, TITLE_PROFILE)
    await provider.close()


class GraphClient:
    def __init__(self, document):
        self.document = document
        self.writes = []
        self.ignore_write = False
        self.truncated = False

    @asynccontextmanager
    async def transaction(self):
        original = self.document
        try:
            yield self
        except BaseException:
            self.document = original
            raise

    async def query(self, statement, params):
        rows = []
        if self.document is not None and params["document_id"] == str(self.document.id):
            key = "content" if "SELECT content" in statement else "title"
            rows = [{key: getattr(self.document, key)}]
        return {"result": rows, "truncated": self.truncated}

    async def command(self, statement, params, *, language):
        self.writes.append((statement, params, language))
        if not self.ignore_write:
            self.document = self.document.model_copy(update={"title": params["title"]})
        return {"result": []}


async def test_graph_adapter_patches_only_existing_title_and_verifies_write(layer):
    client = GraphClient(layer.document)
    store = ArcadeDBDocumentTitleStore(client)
    updated = layer.document.model_copy(update={"title": "Un título nuevo"})
    await store.update_title(updated)
    await store.update_title(updated)
    assert client.document == updated
    assert client.writes[0][0] == "MATCH (d:Document {id:$document_id}) SET d.title=$title"


@pytest.mark.parametrize("problem", ["missing", "changed", "truncated", "ignored"])
async def test_graph_adapter_rejects_missing_changed_or_unverified_projection(layer, problem):
    client = GraphClient(layer.document)
    if problem == "missing":
        client.document = None
    elif problem == "changed":
        client.document = layer.document.model_copy(update={"content": "Otro original"})
    elif problem == "truncated":
        client.truncated = True
    else:
        client.ignore_write = True
    updated = layer.document.model_copy(update={"title": "Un título nuevo"})
    with pytest.raises(ValueError):
        await ArcadeDBDocumentTitleStore(client).update_title(updated)
    assert len(client.writes) == (1 if problem == "ignored" else 0)
