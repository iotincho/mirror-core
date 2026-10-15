"""Accepted configuration pins the layer and preserves historic capture-only work."""

from types import SimpleNamespace

from src.extractors.document_title import TITLE_PROFILE
from src.extractors.emotions import EMOTIONS_PROFILE
from src.processing.configuration import document_workflow_version
from src.processing.workflows import workflow_extractor
from src.use_cases.submit_processing import workflow_config


def test_new_upload_pins_emotion_profile_provider_and_model(monkeypatch):
    settings = SimpleNamespace(
        openai_transcription_model="transcriber",
        llm_provider="openai",
        openai_model="accepted-model",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        embedding_segmentation_threshold=2000,
        embedding_section_max_tokens=2000,
        embedding_section_target_tokens=1000,
    )
    monkeypatch.setattr("src.use_cases.submit_processing.get_settings", lambda: settings)
    config = workflow_config()
    settings.openai_model = "changed-after-acceptance"
    assert config["extractors"][:1] == [
        {
            "name": "emotions",
            "provider": "openai",
            "model": "accepted-model",
            "profile": EMOTIONS_PROFILE.model_dump(mode="json"),
        }
    ]
    assert config["extractors"][1]["name"] == "document_embeddings"
    assert config["extractors"][1]["configuration"]["segmentation_model"] == "accepted-model"
    assert config["extractors"][2] == {
        "name": "document_title",
        "profile": TITLE_PROFILE.model_dump(mode="json"),
        "provider": "openai",
        "model": "accepted-model",
    }
    assert document_workflow_version(config) == 4
    assert document_workflow_version({"transcription_model": "old"}) == 2
    assert document_workflow_version({"extractors": []}) == 2
    assert document_workflow_version({"document_workflow_version": 4, "extractors": []}) == 2


def test_extraction_factory_uses_accepted_model_and_prompt(monkeypatch, tmp_path):
    captured = []
    provider = SimpleNamespace(provider_name="openai", model_name="accepted-model")

    def configured(name, model):
        captured.append((name, model))
        return provider

    monkeypatch.setattr("src.processing.workflows.emotion_provider_configured", configured)
    runtime = SimpleNamespace(
        document_store=object(),
        context=SimpleNamespace(filesystem_root=tmp_path),
        graph_store=SimpleNamespace(database_client=object()),
    )
    spec = {
        "name": "emotions",
        "provider": "openai",
        "model": "accepted-model",
        "profile": {"id": "accepted-profile", "instructions": "Accepted prompt"},
    }
    extractor = workflow_extractor(runtime, spec, extracting=True)
    assert captured == [("openai", "accepted-model")]
    assert extractor.profile.instructions == "Accepted prompt"
    assert extractor.profile.id == "accepted-profile"
    assert extractor.graph is runtime.graph_store.database_client


def test_persistence_factory_has_no_provider_dependency(monkeypatch, tmp_path):
    def forbidden(*args):
        raise AssertionError("persistence must not construct a model provider")

    monkeypatch.setattr("src.processing.workflows.emotion_provider_configured", forbidden)
    runtime = SimpleNamespace(
        document_store=object(),
        context=SimpleNamespace(filesystem_root=tmp_path),
        graph_store=SimpleNamespace(database_client=object()),
    )
    extractor = workflow_extractor(
        runtime, {"name": "emotions", "profile": EMOTIONS_PROFILE.model_dump()}, extracting=False
    )
    assert extractor.provider is None


def test_title_factory_pins_configuration_and_persistence_needs_no_provider(monkeypatch, tmp_path):
    provider = SimpleNamespace(provider_name="openai", model_name="accepted-model")
    captured = []

    def configured(name, model):
        captured.append((name, model))
        return provider

    monkeypatch.setattr("src.processing.workflows.title_provider_configured", configured)
    runtime = SimpleNamespace(
        document_store=object(),
        context=SimpleNamespace(filesystem_root=tmp_path),
        graph_store=SimpleNamespace(database_client=object()),
    )
    spec = {
        "name": "document_title",
        "profile": TITLE_PROFILE.model_dump(),
        "provider": "openai",
        "model": "accepted-model",
    }
    extractor = workflow_extractor(runtime, spec, extracting=True)
    assert extractor.provider is provider
    assert extractor.profile == TITLE_PROFILE
    assert extractor.store.client is runtime.graph_store.database_client
    later = workflow_extractor(runtime, spec, extracting=False)
    assert later.provider is None
    assert captured == [("openai", "accepted-model")]
