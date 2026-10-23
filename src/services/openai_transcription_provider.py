"""Compatibility constructor; existing path inputs are adapted outside the provider."""


def OpenAITranscriptionProvider(api_key, model, client=None, *, max_retries=2):
    from src.bootstrap.audio import build_legacy_transcriber

    return build_legacy_transcriber(api_key, model, client, max_retries=max_retries)
