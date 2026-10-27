"""The pilot runs against ports alone, without files, engines or provider SDKs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.documents.ports import GraphPersistenceError
from src.core.domain.documents import NewDocument
from src.core.extractors.document_title import DocumentTitle
from src.use_cases.documents.ingest_document import IngestDocument
from src.use_cases.documents.list_documents import ListDocuments
from src.use_cases.extraction.document_title import DocumentTitleExtractor


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Originals:
    def __init__(self):
        self.documents = {}

    async def save(self, document):
        self.documents[document.id] = document

    async def get(self, document_id):
        return self.documents[document_id]

    async def list(self):
        return list(self.documents.values())

    async def update_title(self, document_id, title):
        document = self.documents[document_id].model_copy(update={"title": title})
        self.documents[document_id] = document
        return document


class Artifacts:
    def __init__(self):
        self.outputs = {}

    async def get(self, document_id, run_id):
        return self.outputs.get((document_id, run_id))

    async def save(self, output):
        self.outputs[(output.document_id, output.run_id)] = output


@pytest.mark.anyio
async def test_original_to_title_and_projection_recovery_uses_only_injected_ports():
    originals, artifacts = Originals(), Artifacts()
    ingest = IngestDocument(originals)
    document = await ingest.execute(NewDocument(content="Hoy aprendí a escuchar."))
    provider = SimpleNamespace(
        provider_name="deterministic", model_name="test",
        extract=AsyncMock(return_value=(DocumentTitle(title="Aprender a escuchar"), None)),
    )
    projection = SimpleNamespace(update_title=AsyncMock(side_effect=GraphPersistenceError()))
    output = await DocumentTitleExtractor(originals, artifacts, projection, provider).extract(
        document
    )
    assert (await ingest.get(document.id)).title is None
    # A persistence-only process can recover with neither a provider nor its configuration.
    recovery = DocumentTitleExtractor(originals, artifacts, projection)
    with pytest.raises(GraphPersistenceError):
        await recovery.persist(output)
    projection.update_title.side_effect = None
    await recovery.persist(output)
    current, = await ListDocuments(originals).execute()
    assert current.title == "Aprender a escuchar"
    assert current.model_dump(exclude={"title"}) == document.model_dump(exclude={"title"})
    assert provider.extract.await_count == 1
    projection.update_title.assert_awaited_with(current)


def test_legacy_model_and_error_imports_preserve_runtime_identity():
    from src.core.domain.audio_notes import AudioNote
    from src.core.domain.audio_notes import AudioNote as LegacyAudioNote
    from src.core.domain.documents import Document
    from src.core.domain.documents import Document as LegacyDocument
    from src.core.extractors.document_title import DocumentTitle as LegacyTitle
    from src.core.processing.errors import WorkflowFailure
    from src.core.processing.errors import WorkflowFailure as LegacyFailure

    assert (Document, AudioNote, DocumentTitle, WorkflowFailure) == (
        LegacyDocument, LegacyAudioNote, LegacyTitle, LegacyFailure,
    )
