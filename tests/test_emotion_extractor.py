"""Independent layer contracts, replay, evidence and provider boundaries."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.base import Extractor
from src.extractors.contracts import ExtractorProfile, FrozenModel, ProviderMetadata, content_hash
from src.extractors.emotion_evidence import EmotionEvidenceError, EmotionResponse
from src.extractors.emotions import EMOTIONS_PROFILE, EmotionExtractor, Emotions
from src.extractors.openai_emotions import EmotionProviderError, OpenAIEmotionProvider
from src.extractors.registry import ExtractorRegistry
from src.processing.artifacts import ArtifactCorrupted
from src.services.document_store import FileDocumentStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeEmotions:
    provider_name, model_name = "fake", "test"

    def __init__(self, emotions=None):
        self.calls = 0
        self.payload = EmotionResponse(emotions=emotions or [])

    async def extract(self, document, profile):
        self.calls += 1
        return self.payload, ProviderMetadata(provider="fake", model="test")


@pytest.fixture
async def layer(tmp_path):
    document = build_document(NewDocument(content="Hoy siento alegría. Después sentí miedo."))
    documents = FileDocumentStore(tmp_path / "documents")
    await documents.save(document)
    artifacts = LayerArtifacts(tmp_path / "layers")
    provider = FakeEmotions([{"label": "alegría", "quotes": ["Hoy siento alegría."]}])
    # None is intentional: dry-run must not even initialize the graph schema.
    extractor = EmotionExtractor(documents, artifacts, graph=None, provider=provider)
    return SimpleNamespace(
        document=document,
        documents=documents,
        artifacts=artifacts,
        provider=provider,
        extractor=extractor,
    )


async def test_dry_run_stores_replayable_artifact_and_retry_does_not_call_model(layer):
    run = uuid4()
    first = await layer.extractor.extract(layer.document, run_id=run)
    second = await layer.extractor.extract(layer.document, run_id=run)
    assert first == second == await layer.artifacts.get(layer.document.id, run)
    assert layer.provider.calls == 1
    assert first.content_hash == content_hash(layer.document.content)
    assert first.profile == EMOTIONS_PROFILE and first.extractor == "emotions"


async def test_persist_later_uses_saved_profile_without_provider(layer):
    output = await layer.extractor.extract(layer.document)
    changed = ExtractorProfile(id="emotions/v2", instructions="New instructions")
    later = EmotionExtractor(layer.documents, layer.artifacts, None, profile=changed)
    writes = []

    async def write_layer(saved, payload):
        writes.append((saved.profile, payload))

    later.write_layer = write_layer
    await later.persist(output)
    assert writes[0][0] == EMOTIONS_PROFILE
    assert layer.provider.calls == 1


async def test_retry_refuses_changed_profile_or_model(layer):
    output = await layer.extractor.extract(layer.document)
    layer.extractor.profile = ExtractorProfile(id="emotions/v2", instructions="Changed")
    with pytest.raises(ValueError, match="configuration_changed"):
        await layer.extractor.extract(layer.document, run_id=output.run_id)
    layer.extractor.profile = EMOTIONS_PROFILE
    layer.provider.model_name = "other-model"
    with pytest.raises(ValueError, match="configuration_changed"):
        await layer.extractor.extract(layer.document, run_id=output.run_id)
    assert layer.provider.calls == 1


@pytest.mark.parametrize(
    "content,quote",
    [
        ("Estoy triste.", "Estoy feliz."),
        ("Miedo. Miedo.", "Miedo."),
        ("aaaa", "aaa"),
    ],
)
async def test_rejects_invented_or_ambiguous_literal_evidence(layer, content, quote):
    document = layer.document.model_copy(update={"content": content})
    with pytest.raises(
        EmotionEvidenceError, match="emotion_quote_not_found|emotion_quote_ambiguous"
    ):
        layer.extractor.validate_payload(
            {"emotions": [{"label": "miedo", "quotes": [quote]}]}, document
        )


async def test_rejects_duplicate_evidence_and_blank_labels(layer):
    occurrence = {"label": "alegría", "quotes": ["Hoy siento alegría."]}
    with pytest.raises(ValueError, match="duplicate_emotion"):
        layer.extractor.validate_payload({"emotions": [occurrence, occurrence]}, layer.document)
    with pytest.raises(ValueError, match="invalid_emotion_label"):
        layer.extractor.validate_payload(
            {"emotions": [{**occurrence, "label": " "}]}, layer.document
        )


async def test_empty_is_valid_and_optional_immediate_persistence(layer):
    layer.provider.payload = Emotions(emotions=[])
    writes = []

    async def write_layer(saved, payload):
        assert await layer.artifacts.get(saved.document_id, saved.run_id) == saved
        writes.append(payload)

    layer.extractor.write_layer = write_layer
    result = await layer.extractor.extract(layer.document, dry_run=False)
    assert result.payload == {"emotions": [], "warnings": []} and writes == [Emotions(emotions=[])]


async def test_rejects_source_changed_since_extraction(layer):
    output = await layer.extractor.extract(layer.document)
    updated = layer.document.model_copy(update={"content": "Otra nota."})
    path = layer.documents._directory / f"{updated.id}.json"
    path.write_text(updated.model_dump_json())
    with pytest.raises(ValueError, match="source_changed"):
        await layer.extractor.persist(output)


async def test_rejects_unsaved_modified_foreign_and_corrupted_artifacts(layer, tmp_path):
    output = await layer.extractor.extract(layer.document)
    modified = output.model_copy(update={"payload": {"emotions": []}})
    with pytest.raises(ValueError, match="not_saved_or_changed"):
        await layer.extractor.persist(modified)
    foreign = EmotionExtractor(layer.documents, LayerArtifacts(tmp_path / "other-workspace"), None)
    with pytest.raises(ValueError, match="not_saved_or_changed"):
        await foreign.persist(output)
    storage = layer.artifacts.storage(output.document_id, output.run_id)
    path = storage.directory / "result.json"
    saved = json.loads(path.read_text())
    saved["payload"]["payload"] = {"emotions": []}
    path.write_text(json.dumps(saved))
    with pytest.raises(ArtifactCorrupted):
        await layer.artifacts.get(output.document_id, output.run_id)


async def test_deleting_artifacts_preserves_other_documents(layer):
    output = await layer.extractor.extract(layer.document)
    other = build_document(NewDocument(content="Otro documento"))
    await layer.documents.save(other)
    second = output.model_copy(
        update={
            "run_id": uuid4(),
            "document_id": other.id,
            "content_hash": content_hash(other.content),
            "payload": {"emotions": []},
        }
    )
    await layer.artifacts.save(second)
    await layer.artifacts.delete_for_document(layer.document.id)
    assert await layer.artifacts.get(layer.document.id, output.run_id) is None
    assert await layer.artifacts.get(other.id, second.run_id) == second


async def test_two_different_algorithms_and_schemas_can_run_concurrently(layer):
    class LengthResult(FrozenModel):
        characters: int

    class LengthExtractor(Extractor):
        name = "length_test"

        async def produce(self, document):
            started.set()
            await emotion_started.wait()
            return LengthResult(characters=len(document.content)), None

        def validate_payload(self, payload, document):
            return LengthResult.model_validate(payload)

        async def write_layer(self, output, payload):
            raise AssertionError("dry run")

    started, emotion_started = asyncio.Event(), asyncio.Event()
    original = layer.provider.extract

    async def produce_emotions(document, profile):
        emotion_started.set()
        await started.wait()
        return await original(document, profile)

    layer.provider.extract = produce_emotions
    registry = ExtractorRegistry()
    registry.register("emotions", EmotionExtractor)
    registry.register("length_test", LengthExtractor)
    length = registry.create(
        "length_test",
        documents=layer.documents,
        artifacts=layer.artifacts,
        profile=ExtractorProfile(id="length/test", instructions="Count"),
    )
    emotion = registry.create(
        "emotions",
        documents=layer.documents,
        artifacts=layer.artifacts,
        graph=None,
        provider=layer.provider,
    )
    outputs = await asyncio.wait_for(
        asyncio.gather(length.extract(layer.document), emotion.extract(layer.document)), timeout=2
    )
    assert outputs[0].payload == {"characters": len(layer.document.content)}
    assert outputs[1].payload["emotions"][0]["label"] == "alegría"
    with pytest.raises(ValueError, match="already_registered"):
        registry.register("emotions", EmotionExtractor)


async def test_openai_receives_full_note_own_schema_and_reports_refusal(layer):
    requests = []
    response = SimpleNamespace(
        output_parsed=layer.provider.payload, model="resolved-model", id="response-1", usage=None
    )

    async def parse(**kwargs):
        requests.append(kwargs)
        return response

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    provider = OpenAIEmotionProvider("fake-key", "configured-model", client)
    payload, metadata = await provider.extract(layer.document, EMOTIONS_PROFILE)
    assert requests[0]["input"][1]["content"] == layer.document.content
    assert requests[0]["text_format"] is EmotionResponse and requests[0]["store"] is False
    assert payload == layer.provider.payload and metadata.model == "resolved-model"
    response.output_parsed = None
    with pytest.raises(EmotionProviderError, match="structured emotion result"):
        await provider.extract(layer.document, EMOTIONS_PROFILE)
    await provider.close()  # Borrowed SDK clients are not closed.


async def test_two_named_emotions_can_share_the_same_supporting_sentence(layer):
    document = layer.document.model_copy(update={"content": "Estoy feliz y triste."})
    payload = {
        "emotions": [
            {"label": "felicidad", "quotes": [document.content]},
            {"label": "tristeza", "quotes": [document.content]},
        ]
    }
    assert len(layer.extractor.validate_payload(payload, document).emotions) == 2


async def test_profile_change_during_provider_call_is_not_mistagged(layer):
    original = layer.provider.extract
    run = uuid4()

    async def change_profile(document, profile):
        layer.extractor.profile = ExtractorProfile(
            id="changed", instructions="Changed instructions"
        )
        return await original(document, profile)

    layer.provider.extract = change_profile
    with pytest.raises(ValueError, match="configuration_changed"):
        await layer.extractor.extract(layer.document, run_id=run)
    assert await layer.artifacts.get(layer.document.id, run) is None


@pytest.mark.parametrize("label", ["ALEGRÍA", "alegri\u0301a"])
async def test_rejects_normalized_duplicate_labels_even_with_different_evidence(layer, label):
    with pytest.raises(ValueError, match="duplicate_emotion_label"):
        layer.extractor.validate_payload(
            {
                "emotions": [
                    {"label": "alegría", "quotes": ["Hoy siento alegría."]},
                    {"label": label, "quotes": ["Después sentí miedo."]},
                ]
            },
            layer.document,
        )


async def test_rejects_repeated_quote_within_group(layer):
    with pytest.raises(ValueError, match="duplicate_emotion_quote"):
        layer.extractor.validate_payload(
            {
                "emotions": [
                    {"label": "alegría", "quotes": ["Hoy siento alegría.", "Hoy siento alegría."]}
                ]
            },
            layer.document,
        )


@pytest.mark.parametrize("quotes", [[], [""], ["   "]])
async def test_emotion_requires_nonempty_literal_evidence(layer, quotes):
    with pytest.raises((ValidationError, ValueError)):
        layer.extractor.validate_payload(
            {"emotions": [{"label": "miedo", "quotes": quotes}]}, layer.document
        )


async def test_grouped_payload_retains_all_quotes_and_rejects_old_contract(layer):
    document = layer.document.model_copy(
        update={"content": "Hoy siento alegría. Volví a sentir alegría."}
    )
    payload = {
        "emotions": [
            {"label": "alegría", "quotes": ["Hoy siento alegría.", "Volví a sentir alegría."]}
        ]
    }
    # Local validation checks provenance; semantic grouping is the provider's responsibility.
    assert layer.extractor.validate_payload(payload, document).model_dump() == {
        **payload,
        "warnings": [],
    }
    with pytest.raises(ValidationError):
        layer.extractor.validate_payload({"occurrences": []}, layer.document)
