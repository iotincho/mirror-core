"""Accepted configuration pins the layer and preserves historic capture-only work."""

from types import SimpleNamespace

from src.extractors.emotions import EMOTIONS_PROFILE
from src.processing.configuration import document_workflow_version
from src.processing.workflows import workflow_extractor
from src.use_cases.submit_processing import workflow_config


def test_new_upload_pins_emotion_profile_provider_and_model(monkeypatch):
    settings = SimpleNamespace(
        openai_transcription_model="transcriber",
        llm_provider="openai",
        openai_model="accepted-model",
    )
    monkeypatch.setattr("src.use_cases.submit_processing.get_settings", lambda: settings)
    config = workflow_config()
    settings.openai_model = "changed-after-acceptance"
    assert config["extractors"] == [
        {
            "name": "emotions",
            "provider": "openai",
            "model": "accepted-model",
            "profile": EMOTIONS_PROFILE.model_dump(mode="json"),
        }
    ]
    assert document_workflow_version(config) == 3
    assert document_workflow_version({"transcription_model": "old"}) == 2
    assert document_workflow_version({"extractors": []}) == 2


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
