"""Typed origin of a capture, independent of its journal and extraction."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

ENTRY_TRIGGER_KEY = "entry_trigger"
EmotionKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


class InvitationTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["invitation"]
    invitation_id: UUID
    question_id: UUID | None = None


class EmotionTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["emotion"]
    emotion_key: EmotionKey


class AcceptedEmotionTrigger(EmotionTrigger):
    label: EmotionKey


EntryTriggerInput = Annotated[InvitationTrigger | EmotionTrigger, Field(discriminator="kind")]
EntryTrigger = Annotated[InvitationTrigger | AcceptedEmotionTrigger, Field(discriminator="kind")]


def emotion_trigger_metadata(trigger: AcceptedEmotionTrigger | None) -> dict[str, str]:
    return {ENTRY_TRIGGER_KEY: trigger.model_dump_json()} if trigger is not None else {}


def read_document_trigger(metadata: dict[str, str]) -> EntryTrigger | None:
    """Read accepted metadata, including originals recorded before the typed API."""
    try:
        if metadata.get("invitation_id"):
            return InvitationTrigger(
                kind="invitation",
                invitation_id=metadata["invitation_id"],
                question_id=metadata.get("invitation_question_id"),
            )
        if value := metadata.get(ENTRY_TRIGGER_KEY):
            return AcceptedEmotionTrigger.model_validate_json(value)
    except ValidationError:
        # Historical metadata and portable archives can contain unrecognized values.
        return None
    return None


def manifest_emotion_trigger(manifest: dict) -> AcceptedEmotionTrigger | None:
    value = manifest.get(ENTRY_TRIGGER_KEY)
    return AcceptedEmotionTrigger.model_validate(value) if value is not None else None


def emotion_trigger_manifest(trigger: AcceptedEmotionTrigger) -> dict:
    return {ENTRY_TRIGGER_KEY: trigger.model_dump(mode="json")}
