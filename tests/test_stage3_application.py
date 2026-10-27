"""Audio and extractor workflows run with ports, without paths, tokenizers or engines."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_document_pilot import Artifacts, Originals

from src.core.domain.audio_notes import new_audio_note
from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.document_embeddings import EmbeddingConfiguration, Segmentation
from src.core.extractors.emotion_evidence import EmotionResponse
from src.core.processing.errors import WorkflowFailure, WorkflowWaiting
from src.core.processing.models import ProcessingJob
from src.use_cases.audio.process_audio_note import ProcessAudioNote
from src.use_cases.extraction.document_embeddings import DocumentEmbeddingExtractor
from src.use_cases.extraction.emotions import EmotionExtractor


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Checkpoints:
    def __init__(self):
        self.values = {}

    async def read(self, name, identity):
        return self.values.get((name, identity))

    async def write(self, name, identity, payload):
        self.values[(name, identity)] = payload


class LayerArtifacts(Artifacts):
    def __init__(self):
        super().__init__()
        self.checkpoints = {}

    def storage(self, document_id, run_id):
        return self.checkpoints.setdefault((document_id, run_id), Checkpoints())


@pytest.mark.anyio
async def test_emotions_keep_checkpoints_and_persist_without_repeating_the_provider():
    originals, artifacts = Originals(), LayerArtifacts()
    document = build_document(NewDocument(content="Hoy siento alegría."))
    await originals.save(document)
    provider = SimpleNamespace(
        provider_name="fake",
        model_name="test",
        extract=AsyncMock(
            return_value=(
                EmotionResponse(
                    emotions=[
                        {
                            "label": "alegría",
                            "quotes": [document.content],
                        }
                    ]
                ),
                None,
            ),
        ),
    )
    projection = SimpleNamespace(persist=AsyncMock(side_effect=ConnectionError()))
    case = EmotionExtractor(originals, artifacts, projection, provider)
    output = await case.extract(document)
    with pytest.raises(ConnectionError):
        await case.persist(output)
    projection.persist.side_effect = None
    await EmotionExtractor(originals, artifacts, projection).persist(output)
    assert provider.extract.await_count == 1
    assert await originals.get(document.id) == document
    assert len(artifacts.storage(document.id, output.run_id).values) == 1


@pytest.mark.anyio
async def test_embedding_algorithm_accepts_a_counter_port_and_preserves_unicode_offsets():
    originals, artifacts = Originals(), Artifacts()
    document = build_document(NewDocument(content="ñá🙂" * 60))
    await originals.save(document)
    provider = SimpleNamespace(
        segment=AsyncMock(return_value=Segmentation(sections=[])),
        embed=AsyncMock(side_effect=lambda texts, _: [[1.0, 0.0, 0.0] for text in texts]),
    )
    store = SimpleNamespace(existing=AsyncMock(return_value=None), persist=AsyncMock())
    case = DocumentEmbeddingExtractor(
        originals,
        artifacts,
        store,
        EmbeddingConfiguration(
            segmentation_model="test", dimensions=3, section_max_tokens=64, section_target_tokens=32
        ),
        provider,
        token_count=len,
    )
    output = await case.extract(document)
    assert "".join(section["text"] for section in output.payload["sections"]) == document.content
    assert all(section["tokens"] <= 64 for section in output.payload["sections"])
    for section in output.payload["sections"]:
        assert document.content[section["start_char"] : section["end_char"]] == section["text"]
    await case.persist(output)
    store.persist.assert_awaited_once()


@pytest.mark.anyio
async def test_audio_recovers_after_graph_failure_without_a_path_or_another_transcription():
    note = new_audio_note("voice.webm", "audio/webm", 4, None)
    originals, checkpoints = Originals(), Checkpoints()
    source = object()

    async def get_note(_):
        return note

    async def save_note(updated):
        nonlocal note
        note = updated

    audio = SimpleNamespace(
        get=get_note,
        save=save_note,
        original_sha256=AsyncMock(return_value="original-checksum"),
        transcription_source=lambda _: source,
    )
    graph = SimpleNamespace(persist_document=AsyncMock(side_effect=ConnectionError()))
    runtime = SimpleNamespace(document_store=originals, audio_note_store=audio, graph_store=graph)

    @asynccontextmanager
    async def resolve(_):
        yield runtime

    provider = SimpleNamespace(
        provider_name="synthetic",
        model_name="accepted-model",
        transcribe=AsyncMock(return_value="Una transcripción original."),
    )
    context = SimpleNamespace(
        record=ProcessingJob(
            user_id=uuid4(),
            workflow="audio",
            workflow_version=2,
            resource_kind="audio",
            resource_id=note.id,
            stage="transcription",
        ),
        assert_lease=AsyncMock(),
        repository=SimpleNamespace(child_and_wait=AsyncMock()),
    )

    async def advance(stage, **values):
        context.record.stage = stage
        context.record.checkpoints.update(values)

    context.advance = advance
    case = ProcessAudioNote(
        resolve,
        lambda _: provider,
        artifacts_factory=lambda *_: checkpoints,
        failure_for=lambda *_: WorkflowFailure("graph_unavailable", retry_delay=10),
    )
    with pytest.raises(WorkflowFailure, match="graph_unavailable"):
        await case.execute(context)
    assert note.transcript and context.record.stage == "document_creation"
    graph.persist_document.side_effect = None

    def no_provider(_):
        raise AssertionError("Recovery must not construct a transcriber")

    case.provider_factory = no_provider
    with pytest.raises(WorkflowWaiting):
        await case.execute(context)
    provider.transcribe.assert_awaited_once_with(source)
    assert (await originals.get(note.id)).content == note.transcript
    assert note.document_id == note.id and note.status == "completed"
    context.repository.child_and_wait.assert_awaited_once()
