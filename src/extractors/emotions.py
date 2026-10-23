"""Compatibility imports; use the canonical layers for new code."""

from src.core.extractors.emotion_evidence import Emotions as Emotions
from src.core.extractors.emotions import EMOTIONS_PROFILE as EMOTIONS_PROFILE
from src.core.extractors.emotions import EmotionProvider as EmotionProvider


def EmotionExtractor(documents, artifacts, graph, provider=None, profile=EMOTIONS_PROFILE):
    from src.bootstrap.extraction import build_emotion_extractor

    return build_emotion_extractor(documents, artifacts, graph, provider, profile)
