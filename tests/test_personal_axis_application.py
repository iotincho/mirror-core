"""Accepted identity and durable artifacts survive the first axis migration stage."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from src.adapters.providers.openai.personal_axes import GENERATOR_RULES, OpenAIAxisProvider
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap import personal_axes as composition
from src.core.domain.documents import Document
from src.core.extractors.contracts import ExtractionOutput
from src.core.extractors.personal_axes.models import (
    AxisError,
    AxisSpecification,
    AxisWriteContext,
    Criterion,
    FindingsResponse,
    PreviewRequest,
)
from src.core.extractors.personal_axes.profiles import EXTRACTION_RULES, VOICE_RULES
from src.use_cases.extraction.personal_axis import PersonalAxisExtractor
from src.use_cases.personal_axes.build_specification import build_specification

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_pre_migration_profile_and_request_fingerprints_remain_identical():
    before = json.loads((FIXTURES / "personal_axes_contract_v1.json").read_text())

    class Generator:
        async def generate_criterion(self, data):
            assert data == {
                "purpose": "Recuperar ideas",
                "adjustments": [],
                "previous_instructions": None,
            }
            return Criterion(instructions="Recuperar ideas explícitas."), None

    request = PreviewRequest.model_validate(before["request"])
    spec, _ = await build_specification(Generator(), request, {"model": "fixture-model"})
    assert request.fingerprint == before["request_hash"]
    assert spec.fingerprint == before["specification_hash"]
    assert spec.profile.fingerprint == before["profile_hash"]
    for key, text in (
        ("voice_hash", VOICE_RULES),
        ("extraction_rules_hash", EXTRACTION_RULES),
        ("generator_rules_hash", GENERATOR_RULES),
    ):
        assert hashlib.sha256(text.encode()).hexdigest() == before[key]


@pytest.mark.anyio
async def test_pre_migration_artifact_recovers_persistence_with_no_provider(tmp_path, monkeypatch):
    before = json.loads((FIXTURES / "personal_axes_artifact_v1.json").read_text())
    document = Document.model_validate(before["document"])
    output = ExtractionOutput.model_validate(before["output"])
    specification = AxisSpecification.model_validate(before["specification"])
    documents, artifacts = (
        FileDocumentStore(tmp_path / "documents"),
        LayerArtifacts(tmp_path / "layers"),
    )
    await documents.save(document)
    await artifacts.save(output)
    writes = []

    class Projection:
        async def write(self, actual, payload, axis_id, version_id, *, context):
            assert actual == output
            assert payload.findings[0].evidence[0].quote == document.content
            assert axis_id == UUID(output.request_config["axis_id"])
            assert version_id == UUID(output.request_config["version_id"])
            assert context == AxisWriteContext(
                "000000000001:original-reservation", ((str(version_id), 1),)
            )
            writes.append(actual)
            if len(writes) == 1:
                raise ConnectionError("synthetic interrupted graph write")
            return True

    runtime = SimpleNamespace(
        document_store=documents,
        graph_store=SimpleNamespace(database_client=object()),
        context=SimpleNamespace(filesystem_root=tmp_path),
    )

    def unexpected_provider(_):
        raise AssertionError("Persistence recovery must not construct a provider")

    monkeypatch.setattr(composition, "get_axis_provider", unexpected_provider)
    monkeypatch.setattr(composition, "ArcadeDBAxisStore", lambda _: Projection())

    def resume():
        extractor = composition.build_personal_axis_extractor(
            runtime,
            {
                "specification": specification.model_dump(mode="json"),
                "axis_id": output.request_config["axis_id"],
                "version_id": output.request_config["version_id"],
            },
            extracting=False,
            artifacts=artifacts,
            write_context=AxisWriteContext(
                "000000000001:original-reservation", ((output.request_config["version_id"], 1),)
            ),
        )
        return extractor

    with pytest.raises(ConnectionError):
        await resume().persist(output)
    restored = resume()
    assert isinstance(restored, PersonalAxisExtractor)
    assert await restored.extract(document, run_id=output.run_id) == output
    await restored.persist(output)
    assert len(writes) == 2
    assert (await documents.get(document.id)).content == document.content
    assert await artifacts.get(document.id, output.run_id) == output


@pytest.mark.anyio
async def test_provider_borrows_injected_client_and_owns_created_client(monkeypatch):
    result = SimpleNamespace(status="completed", output_parsed=FindingsResponse(findings=[]))
    injected = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=result)), close=AsyncMock()
    )
    provider = OpenAIAxisProvider(
        None, "fixture-model", client=injected, timeout_seconds=37, max_concurrency=2
    )
    from src.core.extractors.contracts import ExtractorProfile

    profile = ExtractorProfile(id="fixture", instructions="Synthetic criterion")
    await provider.extract(SimpleNamespace(content="Synthetic source"), profile)
    await provider.close()
    injected.close.assert_not_awaited()

    created = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=result)), close=AsyncMock()
    )
    factory = []

    def create(**kwargs):
        factory.append(kwargs)
        return created

    monkeypatch.setattr("openai.AsyncOpenAI", create)
    provider = OpenAIAxisProvider(
        "synthetic", "fixture-model", timeout_seconds=37, max_concurrency=2
    )
    await provider.extract(SimpleNamespace(content="Synthetic source"), profile)
    await provider.close()
    await provider.close()
    created.close.assert_awaited_once()
    assert factory == [{"api_key": "synthetic", "timeout": 37, "max_retries": 0}]
    assert created.responses.parse.call_args.kwargs["store"] is False


@pytest.mark.anyio
async def test_process_composition_reuses_provider_and_closes_it_once(monkeypatch):
    await composition.close_axis_providers()
    provider = SimpleNamespace(close=AsyncMock())

    # A real provider instance is hashable; use a tiny owned test double too.
    class Provider:
        close = provider.close

    shared = Provider()
    builds = []

    def create(*args):
        builds.append(args)
        return shared

    monkeypatch.setattr(composition, "build_axis_provider", create)
    monkeypatch.setattr(
        composition, "get_settings", lambda: SimpleNamespace(openai_api_key="synthetic")
    )
    config = {"provider": "openai", "model": "fixture-model", "max_output_tokens": 6000}
    try:
        assert composition.get_axis_provider(config) is shared
        assert composition.get_axis_provider(config) is shared
        assert builds == [("synthetic", "fixture-model", 6000)]
    finally:
        await composition.close_axis_providers()
    shared.close.assert_awaited_once()


def test_canonical_error_is_semantic_and_legacy_http_translation_remains_available():
    from src.extractors.personal_axes.contracts import AxisError as LegacyAxisError

    assert not hasattr(AxisError("axis_preview_expired"), "status")
    legacy = LegacyAxisError("axis_preview_expired", 410)
    assert isinstance(legacy, AxisError)
    assert legacy.status == 410 and legacy.code == "axis_preview_expired"
