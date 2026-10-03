import pytest
from pydantic import ValidationError

from src.domain.documents import NewDocument
from src.extraction.contracts import Concept, Evidence, ExtractionResult
from src.extraction.profiles import PROFILES
from src.services.document_store import DocumentNotFoundError, FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.services.structured_extractor import ProviderExtraction, TokenUsage
from src.use_cases.extract_document import ExtractDocument, ExtractionRunFailedError
from src.use_cases.ingest_document import IngestDocument


class TitleExtractor:
    provider_name = "fake"
    model_name = "fake"

    def __init__(self, title: str | None, quote: str = "autonomía") -> None:
        self.title = title
        self.quote = quote

    def extract(self, document, profile) -> ProviderExtraction:
        return ProviderExtraction(
            result=ExtractionResult(
                title=self.title,
                concepts=[Concept(id="1", name="autonomía", evidence=[Evidence(quote=self.quote)])],
                entities=[],
                claims=[],
                relationships=[],
            ),
            provider=self.provider_name,
            model=self.model_name,
            usage=TokenUsage(),
        )


def test_titles_are_normalized_and_bounded_but_old_extractions_still_load() -> None:
    payload = dict(concepts=[], entities=[], claims=[], relationships=[])
    assert ExtractionResult(**payload).title is None
    assert (
        ExtractionResult(title="  Buscar\n más   autonomía  ", **payload).title
        == "Buscar más autonomía"
    )
    for title in ["", "   ", "x" * 81]:
        with pytest.raises(ValidationError):
            ExtractionResult(title=title, **payload)


def test_generated_title_is_persisted_and_reprocessing_preserves_original(tmp_path) -> None:
    store = FileDocumentStore(tmp_path / "documents")
    document = IngestDocument(store).execute(
        NewDocument(
            content="Quiero más autonomía.",
            source="manual",
            metadata={"original": "yes"},
            authored_at="2024-01-10T09:30:00-03:00",
        )
    )
    extractor = TitleExtractor("Buscar más autonomía")
    use_case = ExtractDocument(store, FileExtractionStore(tmp_path / "extractions"), extractor)

    run = use_case.execute(document.id)
    assert run.result.title == store.get(document.id).title == "Buscar más autonomía"
    assert store.get(document.id).model_dump(exclude={"title"}) == document.model_dump(
        exclude={"title"}
    )
    extractor.title = "Una decisión pendiente"
    use_case.execute(document.id)
    assert store.list()[0].title == "Una decisión pendiente"
    assert store.get(document.id).content == document.content

    # A legacy provider without a title must not erase the existing one.
    extractor.title = None
    use_case.execute(document.id)
    assert store.get(document.id).title == "Una decisión pendiente"


def test_invalid_extraction_cannot_replace_the_previous_title(tmp_path) -> None:
    store = FileDocumentStore(tmp_path / "documents")
    document = IngestDocument(store).execute(NewDocument(content="Quiero más autonomía."))
    store.update_title(document.id, "Título anterior")
    use_case = ExtractDocument(
        store,
        FileExtractionStore(tmp_path / "extractions"),
        TitleExtractor("Título nuevo", quote="inventado"),
    )
    with pytest.raises(ExtractionRunFailedError):
        use_case.execute(document.id)
    assert store.get(document.id).title == "Título anterior"


def test_legacy_document_loads_and_title_update_does_not_create_missing_documents(tmp_path) -> None:
    store = FileDocumentStore(tmp_path)
    document = IngestDocument(store).execute(NewDocument(content="Nota antigua."))
    path = tmp_path / f"{document.id}.json"
    path.write_text(document.model_dump_json(exclude={"title"}), encoding="utf-8")
    assert store.get(document.id).title is None
    store.delete(document.id)
    with pytest.raises(DocumentNotFoundError):
        store.update_title(document.id, "Un título")
    assert not path.exists()


def test_every_runtime_profile_requests_a_title_and_records_new_versions() -> None:
    for profile in PROFILES.values():
        assert "3 to 8 words" in profile.instructions
        assert "at most 80 characters" in profile.instructions
        assert profile.schema_version.endswith("-title-v1")
        assert profile.prompt_version.endswith("-title-v1")
