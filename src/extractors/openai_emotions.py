"""Compatibility imports; use the canonical layers for new code."""

from src.adapters.providers.openai.emotions import EmotionProviderError as EmotionProviderError


def OpenAIEmotionProvider(api_key, model, client=None, *, max_retries=2):
    from src.bootstrap.extraction import build_emotions_provider

    return build_emotions_provider(api_key, model, client, max_retries=max_retries)
