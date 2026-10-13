"""Discard empty evidence, repair once and replay durable emotion diagnostics."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ProviderMetadata
from src.extractors.emotion_evidence import EmotionEvidenceError, EmotionResponse
from src.extractors.emotions import EMOTIONS_PROFILE, EmotionExtractor
from src.extractors.openai_emotions import OpenAIEmotionProvider
from src.services.document_store import FileDocumentStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Provider:
    provider_name, model_name = "fake", "test"

    def __init__(self, original, corrected=None):
        self.original = EmotionResponse.model_validate(original)
        self.corrected = corrected
        self.calls = self.corrections = 0

    async def extract(self, document, profile):
        self.calls += 1
        return self.original, ProviderMetadata(provider="fake", model="test", response_id="initial")

    async def correct(self, document, profile, response, issues):
        self.corrections += 1
        assert response == self.original and issues
        if isinstance(self.corrected, Exception):
            raise self.corrected
        return EmotionResponse.model_validate(self.corrected), ProviderMetadata(
            provider="fake", model="test", response_id="corrected"
        )


@pytest.fixture
async def setup(tmp_path):
    document = build_document(
        NewDocument(content="Tengo miedo. Tengo miedo. Al volver sentí miedo.")
    )
    documents = FileDocumentStore(tmp_path / "documents")
    await documents.save(document)
    artifacts = LayerArtifacts(tmp_path / "layers")

    def make(original, corrected=None):
        provider = Provider(original, corrected)
        extractor = EmotionExtractor(documents, artifacts, None, provider)
        return extractor, provider, document

    return make


def result(quotes, label="miedo"):
    return {"emotions": [{"label": label, "quotes": quotes}]}


async def test_empty_quotes_discarded_with_warnings_and_no_correction(setup):
    extractor, provider, document = setup(
        {
            "emotions": [
                {"label": "miedo", "quotes": ["", "Al volver sentí miedo.", " \n "]},
                {"label": "alegría", "quotes": [" "]},
                {"label": "tristeza", "quotes": []},
            ]
        }
    )
    run_id = uuid4()
    output = await extractor.extract(document, run_id=run_id)
    assert output.payload["emotions"] == [{"label": "miedo", "quotes": ["Al volver sentí miedo."]}]
    warnings = output.payload["warnings"]
    assert [w["code"] for w in warnings] == [
        "emotion_quote_empty",
        "emotion_quote_empty",
        "emotion_quote_empty",
        "emotion_without_evidence",
        "emotion_without_evidence",
    ]
    assert [w["emotion_index"] for w in warnings] == [0, 0, 1, 1, 2]
    assert all(w["phase"] == "extraction" for w in warnings)
    assert provider.calls == 1 and provider.corrections == 0
    assert await extractor.extract(document, run_id=run_id) == output
    assert provider.calls == 1
    later = EmotionExtractor(extractor.documents, extractor.artifacts, None)
    writes = []

    async def write(output, payload):
        writes.append(payload)

    later.write_layer = write
    await later.persist(output)
    assert writes[0].model_dump() == output.payload


async def test_all_empty_evidence_is_a_valid_empty_result_with_warnings(setup):
    extractor, provider, document = setup(result(["", " "]))
    output = await extractor.extract(document)
    assert output.payload["emotions"] == [] and len(output.payload["warnings"]) == 3
    assert provider.corrections == 0
    extractor, _, document = setup({"emotions": []})
    empty = await extractor.extract(document)
    assert empty.payload == {"emotions": [], "warnings": []}


@pytest.mark.parametrize(
    "quote,code,matches",
    [
        ("Estoy aterrorizado.", "emotion_quote_not_found", 0),
        ("Tengo miedo.", "emotion_quote_ambiguous", 2),
    ],
)
async def test_single_correction_replays_result_and_keeps_both_responses(
    setup, quote, code, matches
):
    extractor, provider, document = setup(
        result(["", quote]), result(["Al volver sentí miedo.", " "])
    )
    run_id = uuid4()
    output = await extractor.extract(document, run_id=run_id)
    assert provider.calls == provider.corrections == 1
    assert output.payload["emotions"] == result(["Al volver sentí miedo."])["emotions"]
    assert [w["phase"] for w in output.payload["warnings"]] == ["extraction", "correction"]
    assert output.provider.response_id == "corrected"
    storage = extractor.artifacts.storage(document.id, run_id)
    initial = await storage.read("emotion-extraction", str(run_id))
    corrected = await storage.read("emotion-correction", str(run_id))
    assert initial["response"] == result(["", quote])
    assert initial["issues"][1] == dict(
        code=code,
        emotion_index=0,
        quote_index=1,
        label="miedo",
        quote_length=len(quote),
        matches=matches,
    )
    assert initial["provider"]["response_id"] == "initial"
    assert corrected["response"] == result(["Al volver sentí miedo.", " "])
    assert corrected["provider"]["response_id"] == "corrected"
    assert await extractor.extract(document, run_id=run_id) == output
    assert provider.calls == provider.corrections == 1


async def test_failed_correction_has_precise_diagnostics_and_no_third_call_on_replay(setup):
    extractor, provider, document = setup(result(["Tengo miedo."]), result(["Una cita inventada."]))
    run_id = uuid4()
    for _ in range(2):
        with pytest.raises(EmotionEvidenceError) as caught:
            await extractor.extract(document, run_id=run_id)
        assert caught.value.issues[0].code == "emotion_quote_not_found"
        assert "emotion_index=0" in str(caught.value) and "matches=0" in str(caught.value)
        assert "Una cita inventada." not in str(caught.value)
    assert provider.calls == provider.corrections == 1
    assert await extractor.artifacts.get(document.id, run_id) is None
    storage = extractor.artifacts.storage(document.id, run_id)
    assert (await storage.read("emotion-extraction", str(run_id)))["issues"]
    assert (await storage.read("emotion-correction", str(run_id)))["issues"]


async def test_retry_after_artifact_publication_failure_reuses_both_responses(setup):
    extractor, provider, document = setup(
        result(["Tengo miedo."]), result(["Al volver sentí miedo."])
    )
    run_id = uuid4()
    save = extractor.artifacts.save

    async def unavailable(output):
        raise OSError("isolated publication failure")

    extractor.artifacts.save = unavailable
    with pytest.raises(OSError):
        await extractor.extract(document, run_id=run_id)
    extractor.artifacts.save = save
    output = await extractor.extract(document, run_id=run_id)
    assert output.payload["emotions"] == result(["Al volver sentí miedo."])["emotions"]
    assert provider.calls == provider.corrections == 1


async def test_interrupted_correction_cannot_repeat_the_invocation_for_same_run(setup):
    extractor, provider, document = setup(
        result(["Tengo miedo."]), ConnectionError("isolated outage")
    )
    run_id = uuid4()
    with pytest.raises(ConnectionError):
        await extractor.extract(document, run_id=run_id)
    with pytest.raises(ValueError, match="emotion_correction_interrupted"):
        await extractor.extract(document, run_id=run_id)
    assert provider.calls == provider.corrections == 1
    assert await extractor.artifacts.get(document.id, run_id) is None


async def test_saved_diagnostic_cannot_be_reused_with_changed_model(setup):
    extractor, provider, document = setup(result(["Tengo miedo."]), result(["inventada"]))
    run_id = uuid4()
    with pytest.raises(EmotionEvidenceError):
        await extractor.extract(document, run_id=run_id)
    provider.model_name = "other"
    with pytest.raises(ValueError, match="attempt_context_changed"):
        await extractor.extract(document, run_id=run_id)
    assert provider.calls == provider.corrections == 1


async def test_openai_correction_receives_full_note_original_and_precise_errors(setup):
    import json

    from src.extractors.emotion_evidence import evidence_issues

    _, _, document = setup(result(["Tengo miedo."]))
    previous = EmotionResponse.model_validate(result(["Tengo miedo."]))
    requests = []

    async def parse(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            output_parsed=EmotionResponse.model_validate(result(["Al volver sentí miedo."])),
            model="resolved-model",
            id="repair-1",
            usage=None,
        )

    adapter = OpenAIEmotionProvider(
        "fake", "test", SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    response, metadata = await adapter.correct(
        document, EMOTIONS_PROFILE, previous, evidence_issues(previous, document.content)
    )
    request = requests[0]
    data = json.loads(request["input"][1]["content"])
    assert data["document"] == document.content and data["previous_result"] == previous.model_dump()
    assert data["errors"][0]["code"] == "emotion_quote_ambiguous"
    assert request["text_format"] is EmotionResponse and request["store"] is False
    assert metadata.response_id == "repair-1" and len(response.emotions) == 1


@pytest.mark.parametrize(
    "corrected,code",
    [
        (result(["Al volver sentí miedo.", "Al volver sentí miedo."]), "duplicate_emotion_quote"),
        (
            {
                "emotions": [
                    {"label": "miedo", "quotes": ["Al volver sentí miedo."]},
                    {"label": "MIEDO", "quotes": ["Tengo miedo. Tengo miedo."]},
                ]
            },
            "duplicate_emotion_label",
        ),
    ],
)
async def test_corrected_response_must_pass_complete_validation(setup, corrected, code):
    extractor, provider, document = setup(result(["Tengo miedo."]), corrected)
    run_id = uuid4()
    with pytest.raises(ValueError, match=code):
        await extractor.extract(document, run_id=run_id)
    assert await extractor.artifacts.get(document.id, run_id) is None
    assert provider.calls == provider.corrections == 1


async def test_persistence_rejects_bad_evidence_without_calling_correction(setup):
    extractor, provider, document = setup(result(["Al volver sentí miedo."]))
    output = await extractor.extract(document)
    invalid = output.model_copy(update={"run_id": uuid4(), "payload": result(["Inexistente."])})
    await extractor.artifacts.save(invalid)
    with pytest.raises(EmotionEvidenceError, match="emotion_quote_not_found"):
        await extractor.persist(invalid)
    assert provider.calls == 1 and provider.corrections == 0
