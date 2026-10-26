"""Bind speech providers, source preparation and durable audio artifacts explicitly."""


from src.adapters.providers.openai.transcription import OpenAITranscriptionProvider
from src.bootstrap.settings import get_settings


def build_transcriber(api_key, model, client=None, *, max_retries=2):
    settings = get_settings()
    return OpenAITranscriptionProvider(
        api_key,
        model,
        client,
        timeout_seconds=settings.provider_timeout_seconds,
        max_concurrency=settings.provider_max_concurrency,
        max_retries=max_retries,
    )


def build_audio_processor(runtime_factory, provider_factory):
    from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
    from src.bootstrap.failures import failure_for
    from src.bootstrap.processing import protected_runtime
    from src.use_cases.audio.process_audio_note import ProcessAudioNote

    return ProcessAudioNote(
        protected_runtime(runtime_factory),
        provider_factory,
        failure_for=failure_for,
        artifacts_factory=lambda runtime, record: ProcessingArtifacts(
            runtime.context.filesystem_root / "processing" / str(record.id)
        ),
    )
