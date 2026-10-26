from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.contracts import ExtractorProfile, ProviderMetadata
from src.extractors.personal_axes.contracts import (
    AxisSpecification,
    Criterion,
    FindingsResponse,
    PreviewRequest,
)
from src.extractors.personal_axes.extractor import PersonalAxisExtractor
from src.extractors.personal_axes.prompt_builder import VOICE_RULES, build_specification
from src.extractors.personal_axes.provider import AxisProviderError, OpenAIAxisProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Provider:
    def __init__(self):
        self.calls = self.corrections = 0
        self.quote = "Quiero crear un podcast."
        self.interrupt = False

    def result(self, quote=None):
        return FindingsResponse(
            findings=[
                {
                    "title": "Crear",
                    "content": "Una idea para desarrollar.",
                    "evidence": [{"quote": quote if quote is not None else self.quote}],
                    "tags": ["Creación", " CREACIÓN ", "proyecto"],
                }
            ]
        )

    async def extract(self, document, profile):
        self.calls += 1
        return self.result(), ProviderMetadata(provider="test", model="test")

    async def correct(self, document, profile, response, issues):
        self.corrections += 1
        if self.interrupt:
            raise TimeoutError("synthetic")
        return self.result(document.content), ProviderMetadata(provider="test", model="test")


@pytest.fixture
async def layer(tmp_path):
    documents = FileDocumentStore(tmp_path / "documents")
    document = build_document(NewDocument(content="Quiero crear un podcast."))
    await documents.save(document)
    provider = Provider()
    spec = AxisSpecification(
        profile=ExtractorProfile(id="test", instructions="Observar ideas"), model="test"
    )
    extractor = PersonalAxisExtractor(
        documents, LayerArtifacts(tmp_path / "layers"), spec, provider=provider
    )
    return extractor, document, provider


async def test_dry_run_uses_common_artifacts_and_preserves_content(layer):
    extractor, document, provider = layer
    run_id = uuid4()
    output = await extractor.extract(document, dry_run=True, run_id=run_id)
    assert output.extractor == "personal_axis"
    assert output.payload["findings"][0]["tags"] == ["Creación", "proyecto"]
    assert output.payload["findings"][0]["content"] == "Una idea para desarrollar."
    assert await extractor.extract(document, run_id=run_id) == output
    assert provider.calls == 1
    assert await extractor.artifacts.get(document.id, run_id) == output
    with pytest.raises(ValueError, match="axis_active_binding_required"):
        await extractor.persist(output)


async def test_evidence_correction_is_bounded_and_checkpointed(layer):
    extractor, document, provider = layer
    provider.quote = "No está en la nota."
    run_id = uuid4()
    output = await extractor.extract(document, run_id=run_id)
    assert output.payload["warnings"] == ["axis_output_corrected"]
    assert provider.corrections == 1
    await extractor.extract(document, run_id=run_id)
    assert provider.calls == provider.corrections == 1


async def test_interrupted_correction_requires_a_new_run(layer):
    extractor, document, provider = layer
    provider.quote, provider.interrupt = "No está en la nota.", True
    run_id = uuid4()
    with pytest.raises(TimeoutError):
        await extractor.extract(document, run_id=run_id)
    with pytest.raises(ValueError, match="axis_correction_interrupted"):
        await extractor.extract(document, run_id=run_id)
    assert provider.calls == provider.corrections == 1


async def test_configuration_and_source_changes_do_not_reuse_artifacts(layer):
    extractor, document, provider = layer
    run_id = uuid4()
    await extractor.extract(document, run_id=run_id)
    other = PersonalAxisExtractor(
        extractor.documents,
        extractor.artifacts,
        extractor.specification.model_copy(update={"model": "different"}),
        provider=provider,
    )
    with pytest.raises(ValueError, match="run_configuration_changed"):
        await other.extract(document, run_id=run_id)
    changed = document.model_copy(update={"content": "Otra nota"})
    with pytest.raises(ValueError, match="source_changed"):
        await extractor.extract(changed, run_id=run_id)
    assert provider.calls == 1


@pytest.mark.parametrize("quote", ["", "   ", "ausente", "a"])
async def test_invalid_evidence_is_not_silently_empty(layer, quote):
    extractor, document, _ = layer
    with pytest.raises(ValueError, match="axis_evidence_invalid"):
        extractor.validate_payload(
            {
                "findings": [
                    {
                        "title": "Idea",
                        "content": "Contenido",
                        "evidence": [{"quote": quote}],
                        "tags": ["idea"],
                    }
                ]
            },
            document,
        )
    assert extractor.validate_payload({"findings": []}, document).findings == []


async def test_input_limit_precedes_provider_call(layer):
    extractor, document, provider = layer
    long = document.model_copy(update={"id": uuid4(), "content": "x" * 100001})
    await extractor.documents.save(long)
    with pytest.raises(ValueError, match="axis_input_too_long"):
        await extractor.extract(long)
    assert provider.calls == 0


async def test_provider_rejects_incomplete_response_and_disables_retention():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="incomplete", output_parsed=FindingsResponse(findings=[]))

    provider = OpenAIAxisProvider(
        None, "test", client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    with pytest.raises(AxisProviderError, match="incomplete"):
        await provider.extract(
            SimpleNamespace(content="nota"), ExtractorProfile(id="test", instructions="criterio")
        )
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 6000


@pytest.mark.parametrize("size", range(1, 6))
async def test_request_accepts_one_to_five_distinct_notes(size):
    ids = [uuid4() for _ in range(size)]
    request = PreviewRequest(
        draft_id=uuid4(), revision=1, title="Ideas", purpose="Ideas", document_ids=ids
    )
    assert request.document_ids == ids


@pytest.mark.parametrize("size", [0, 6])
async def test_request_rejects_empty_or_oversized_samples(size):
    with pytest.raises(ValueError):
        PreviewRequest(
            draft_id=uuid4(),
            revision=1,
            title="Ideas",
            purpose="Ideas",
            document_ids=[uuid4() for _ in range(size)],
        )


@pytest.mark.parametrize("size", range(2, 6))
async def test_request_rejects_duplicate_notes(size):
    with pytest.raises(ValueError, match="requires_distinct_notes"):
        PreviewRequest(
            draft_id=uuid4(),
            revision=1,
            title="Ideas",
            purpose="Ideas",
            document_ids=[uuid4()] * size,
        )


@pytest.mark.parametrize(
    "source,content",
    [
        (
            'Me recuerdo que vos también podés descansar. Ana dijo: "tú nunca paras".',
            "Te recordás que también podés descansar.",
        ),
        (
            'Me recuerdo que tú también puedes descansar. Ana dijo: "vos no parás".',
            "Te recuerdas que también puedes descansar.",
        ),
        (
            'Me recuerdo que usted también puede descansar. Ana dijo: "tú nunca paras".',
            "Usted también puede darse un descanso.",
        ),
        (
            'No sé si me hace bien. Ana dijo: "vos podés seguir".',
            "Todavía no está claro si te hace bien.",
        ),
    ],
)
async def test_personal_voice_reaches_initial_and_corrected_provider_requests(source, content):
    requests = []
    result = FindingsResponse(
        findings=[
            {
                "title": "Compartir tiempo",
                "content": content,
                "tags": ["tiempo"],
                "evidence": [{"quote": source}],
            }
        ]
    )

    async def parse(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=result)

    class Generator:
        async def generate_criterion(self, data):
            assert data["purpose"] == "Reconocer qué me hace bien"
            return Criterion(
                instructions="Observar experiencias de bienestar sin resolver dudas."
            ), None

    profile = (
        await build_specification(
            Generator(),
            SimpleNamespace(purpose="Reconocer qué me hace bien", adjustments=[]),
            {"model": "test"},
        )
    )[0].profile
    provider = OpenAIAxisProvider(
        None, "test", client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    document = SimpleNamespace(content=source)
    initial, _ = await provider.extract(document, profile)
    corrected, _ = await provider.correct(document, profile, initial, [{"code": "test"}])
    assert (
        initial.findings[0].evidence[0].quote == corrected.findings[0].evidence[0].quote == source
    )
    assert initial.findings[0].content == corrected.findings[0].content == content
    assert profile.instructions.count(VOICE_RULES) == 1
    assert profile.instructions.endswith("Observar experiencias de bienestar sin resolver dudas.")
    for request in requests:
        assert VOICE_RULES in request["input"][0]["content"]
        assert request["store"] is False
