"""Emotion-owned provider response, validated payload and evidence diagnostics."""

from typing import Annotated, Literal

from pydantic import Field

from src.extractors.contracts import FrozenModel


class EmotionResponseItem(FrozenModel):
    label: str = Field(min_length=1, max_length=80)
    quotes: list[str]


class EmotionResponse(FrozenModel):
    # Empty evidence is accepted at the provider boundary so it can be discarded locally.
    emotions: list[EmotionResponseItem]


class Emotion(FrozenModel):
    label: str = Field(min_length=1, max_length=80)
    quotes: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class EmotionIssue(FrozenModel):
    code: Literal["emotion_quote_empty", "emotion_quote_not_found", "emotion_quote_ambiguous"]
    emotion_index: int
    quote_index: int
    label: str
    quote_length: int
    matches: int


class EmotionWarning(FrozenModel):
    code: Literal["emotion_quote_empty", "emotion_without_evidence"]
    phase: Literal["extraction", "correction"]
    emotion_index: int
    quote_index: int | None = None
    label: str


class Emotions(FrozenModel):
    emotions: list[Emotion]
    warnings: list[EmotionWarning] = Field(default_factory=list)


class EmotionEvidenceError(ValueError):
    def __init__(self, issues: list[EmotionIssue]):
        self.issues = issues
        # Include locations and counts, never the note or quote itself, in traceback logs.
        super().__init__(
            "; ".join(
                f"{issue.code}: emotion_index={issue.emotion_index} label={issue.label!r} "
                f"quote_index={issue.quote_index} quote_length={issue.quote_length} "
                f"matches={issue.matches}"
                for issue in issues
            )
        )


def evidence_issues(response, content):
    issues = []
    for emotion_index, emotion in enumerate(response.emotions):
        for quote_index, quote in enumerate(emotion.quotes):
            matches, offset = 0, 0
            if quote.strip():
                while (start := content.find(quote, offset)) >= 0:
                    matches += 1
                    offset = start + 1  # Count overlapping occurrences too.
            code = (
                "emotion_quote_empty"
                if not quote.strip()
                else "emotion_quote_not_found"
                if matches == 0
                else "emotion_quote_ambiguous"
                if matches > 1
                else None
            )
            if code:
                issues.append(
                    EmotionIssue(
                        code=code,
                        emotion_index=emotion_index,
                        quote_index=quote_index,
                        label=emotion.label,
                        quote_length=len(quote),
                        matches=matches,
                    )
                )
    return issues


def discard_empty_evidence(response: EmotionResponse, phase):
    emotions, warnings = [], []
    for emotion_index, emotion in enumerate(response.emotions):
        quotes = []
        for quote_index, quote in enumerate(emotion.quotes):
            if quote.strip():
                quotes.append(quote)
            else:
                warnings.append(
                    EmotionWarning(
                        code="emotion_quote_empty",
                        phase=phase,
                        emotion_index=emotion_index,
                        quote_index=quote_index,
                        label=emotion.label,
                    )
                )
        if quotes:
            emotions.append(Emotion(label=emotion.label, quotes=quotes))
        else:
            warnings.append(
                EmotionWarning(
                    code="emotion_without_evidence",
                    phase=phase,
                    emotion_index=emotion_index,
                    label=emotion.label,
                )
            )
    return Emotions(emotions=emotions, warnings=warnings)
