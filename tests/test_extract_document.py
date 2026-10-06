from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.documents import Document, NewDocument
from src.extraction.contracts import Concept, Evidence, ExtractionResult
from src.extraction.profiles import V3_PROFILE, V4_PROFILE
from src.services.document_store import FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.services.openai_extractor import OpenAIExtractor
from src.services.structured_extractor import ProviderExtraction, TokenUsage
from src.use_cases.extract_document import (
    ExtractDocument,
    ExtractionEvidenceError,
    ExtractionRunFailedError,
    resolve_evidence,
)
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document import IngestDocument


class FakeExtractor:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    async def extract(self, document: Document, profile) -> ProviderExtraction:
        return ProviderExtraction(
            result=self._result,
            provider=self.provider_name,
            model=self.model_name,
            response_id="fake-response",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )


def source_document(content: str) -> Document:
    return Document(
        id=uuid4(),
        content=content,
        source="test",
        metadata={},
        created_at="2026-09-22T00:00:00Z",
    )


def valid_result(content: str) -> ExtractionResult:
    quote = "autonomía"
    evidence = Evidence(quote=quote)
    return ExtractionResult(
        concepts=[Concept(id="concept_1", name=quote, evidence=[evidence])],
        entities=[],
        claims=[],
        relationships=[],
    )


@pytest.mark.anyio
async def test_extract_document_records_a_versioned_completed_run(tmp_path) -> None:
    document = source_document("Quiero más autonomía.")
    document_store = FileDocumentStore(tmp_path / "documents")
    extraction_path = tmp_path / "extractions"
    await document_store.save(document)
    use_case = ExtractDocument(
        document_store,
        FileExtractionStore(extraction_path),
        FakeExtractor(valid_result(document.content)),
    )

    run = await use_case.execute(document.id)

    assert run.status == "completed"
    assert run.profile_name == "v4"
    assert run.schema_version == "v2-title-v1"
    assert run.result is not None
    assert run.result.concepts[0].name == "autonomía"
    assert run.result.concepts[0].evidence[0].start_char == 11
    assert run.result.concepts[0].evidence[0].end_char == 20
    assert run.result.concepts[0].evidence[0].start_line == 1
    assert (extraction_path / str(document.id) / f"{run.id}.json").is_file()


@pytest.mark.anyio
async def test_extract_document_records_failure_when_evidence_does_not_match(
    tmp_path, caplog
) -> None:
    document = source_document("Quiero más autonomía.")
    document_store = FileDocumentStore(tmp_path / "documents")
    extraction_store = FileExtractionStore(tmp_path / "extractions")
    await document_store.save(document)
    invalid_result = valid_result(document.content).model_copy(
        update={
            "concepts": [
                Concept(
                    id="concept_1",
                    name="autonomía",
                    evidence=[Evidence(quote="otra")],
                )
            ]
        }
    )
    use_case = ExtractDocument(document_store, extraction_store, FakeExtractor(invalid_result))

    caplog.set_level("ERROR", logger="src.use_cases.extract_document")
    with pytest.raises(ExtractionRunFailedError) as error:
        await use_case.execute(document.id)

    saved = next((tmp_path / "extractions" / str(document.id)).glob("*.json"))
    assert error.value.run_id
    assert '"status": "failed"' in saved.read_text(encoding="utf-8")
    assert '"error": "ExtractionEvidenceError"' in saved.read_text(encoding="utf-8")
    assert "extraction_failed" in caplog.text
    assert "Traceback" in caplog.text
    assert "extraction_failed_result" in caplog.text


@pytest.mark.anyio
async def test_openai_extractor_uses_structured_output_contract() -> None:
    content = "Quiero más autonomía."
    document = source_document(content)
    expected = valid_result(content)
    captured: dict[str, object] = {}

    class FakeResponses:
        async def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=expected,
                model="configured-model",
                id="resp_test",
                usage=SimpleNamespace(input_tokens=12, output_tokens=7),
            )

    extractor = OpenAIExtractor(
        api_key="unused-in-test",
        model="configured-model",
        client=SimpleNamespace(responses=FakeResponses()),
    )

    extraction = await extractor.extract(document, V3_PROFILE)

    assert captured["text_format"] is ExtractionResult
    assert extraction.result == expected
    assert extraction.usage == TokenUsage(input_tokens=12, output_tokens=7)


def test_v4_profile_forbids_editorial_evidence_notation() -> None:
    assert "never use brackets" in V4_PROFILE.instructions
    assert "mudarm[e]" in V4_PROFILE.instructions


def test_v3_profile_requires_verbatim_evidence_quotes() -> None:
    assert "hard requirement" in V3_PROFILE.instructions
    assert "Never correct, normalize" in V3_PROFILE.instructions
    assert "character-for-character" in V3_PROFILE.instructions


def test_resolve_evidence_rejects_an_ambiguous_quote() -> None:
    result = ExtractionResult(
        concepts=[Concept(id="concept_1", name="nota", evidence=[Evidence(quote="nota")])],
        entities=[],
        claims=[],
        relationships=[],
    )

    with pytest.raises(ExtractionEvidenceError, match="ambiguous"):
        resolve_evidence("Una nota y otra nota.", result)


def test_resolve_evidence_discards_provider_offsets() -> None:
    result = ExtractionResult(
        concepts=[
            Concept(
                id="concept_1",
                name="autonomía",
                evidence=[Evidence(quote="autonomía", start_char=60, end_char=69)],
            )
        ],
        entities=[],
        claims=[],
        relationships=[],
    )

    resolved = resolve_evidence("Quiero más autonomía.", result)

    assert resolved.concepts[0].evidence[0].start_char == 11
    assert resolved.concepts[0].evidence[0].end_char == 20


@pytest.mark.anyio
async def test_ingest_and_extract_logs_the_completed_result(tmp_path, caplog) -> None:
    document = source_document("Quiero más autonomía.")
    document_store = FileDocumentStore(tmp_path / "documents")
    process = IngestAndExtractDocument(
        IngestDocument(document_store),
        ExtractDocument(
            document_store,
            FileExtractionStore(tmp_path / "extractions"),
            FakeExtractor(valid_result(document.content)),
        ),
    )

    caplog.set_level("INFO", logger="src.use_cases.ingest_and_extract_document")
    processed = await process.execute(NewDocument(content=document.content, source="test"))

    assert processed.extraction.status == "completed"
    assert "extraction_completed" in caplog.text
    assert '"concepts"' in caplog.text


def test_resolve_evidence_accepts_unicode_canonical_equivalence_and_preserves_source() -> None:
    result = ExtractionResult(
        concepts=[
            Concept(
                id="concept_1",
                name="autonomía",
                evidence=[Evidence(quote="autonomi\u0301a")],
            )
        ],
        entities=[],
        claims=[],
        relationships=[],
    )

    resolved = resolve_evidence("Quiero más autonomía.", result)

    assert resolved.concepts[0].evidence[0].quote == "autonomía"
    assert resolved.concepts[0].evidence[0].start_char == 11
