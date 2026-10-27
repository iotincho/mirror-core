"""Checkpointed extraction/correction and persistence through emotion-owned ports."""

from src.core.extractors.contracts import ProviderMetadata, content_hash
from src.core.extractors.emotion_evidence import (
    EmotionEvidenceError,
    EmotionResponse,
    discard_empty_evidence,
    evidence_issues,
)
from src.core.extractors.emotions import EMOTIONS_PROFILE, label_key, validate_emotions
from src.use_cases.extraction.base import Extractor


class EmotionExtractor(Extractor):
    name = "emotions"

    def __init__(self, documents, artifacts, store, provider=None, profile=EMOTIONS_PROFILE):
        super().__init__(documents, artifacts, profile)
        self.store, self.provider = store, provider

    @property
    def request_config(self):
        if self.provider is None:
            return {}
        return {"provider": self.provider.provider_name, "model": self.provider.model_name}

    async def produce(self, document):
        if self.provider is None:
            raise ValueError("emotion_provider_required")
        return await self.provider.extract(document, self.profile)

    async def produce_for_run(self, document, run_id):
        profile, configuration = self.profile, dict(self.request_config)
        storage = self.artifacts.storage(document.id, run_id)
        identity = str(run_id)
        context = {
            "document_id": str(document.id),
            "run_id": identity,
            "content_hash": content_hash(document.content),
            "profile_hash": profile.fingerprint,
            "profile": profile.model_dump(mode="json"),
            "request_config": configuration,
            "policy": "emotion-evidence/1",
        }

        def verify_context(saved):
            if saved["context"] != context:
                raise ValueError("emotion_attempt_context_changed")

        def verify_configuration():
            if self.profile != profile or self.request_config != configuration:
                raise ValueError("run_configuration_changed")

        async def attempt(phase):
            name = f"emotion-{phase}"
            saved = await storage.read(name, identity)
            if saved is None:
                if phase == "extraction":
                    raw, metadata = await self.produce(document)
                else:
                    # The durable marker caps correction at one invocation per run, even if
                    # the process dies or transport fails before the response is saved.
                    requested = await storage.read("emotion-correction-requested", identity)
                    if requested is not None:
                        verify_context(requested)
                        raise ValueError(
                            "emotion_correction_interrupted; start a new extraction run"
                        )
                    verify_configuration()
                    await storage.write(
                        "emotion-correction-requested", identity, {"context": context}
                    )
                    raw, metadata = await self.provider.correct(document, profile, initial, issues)
                verify_configuration()
                raw = EmotionResponse.model_validate(raw.model_dump(include={"emotions"}))
                found = evidence_issues(raw, document.content)
                prepared = discard_empty_evidence(raw, phase)
                saved = {
                    "context": context,
                    "response": raw.model_dump(mode="json"),
                    "provider": metadata.model_dump(mode="json") if metadata else None,
                    "issues": [item.model_dump(mode="json") for item in found],
                    "warnings": [item.model_dump(mode="json") for item in prepared.warnings],
                }
                await storage.write(name, identity, saved)
            verify_context(saved)
            return (
                EmotionResponse.model_validate(saved["response"]),
                ProviderMetadata.model_validate(saved["provider"]) if saved["provider"] else None,
            )

        initial, metadata = await attempt("extraction")
        prepared = discard_empty_evidence(initial, "extraction")
        issues = [
            i for i in evidence_issues(initial, document.content) if i.code != "emotion_quote_empty"
        ]
        if issues:
            corrected, metadata = await attempt("correction")
            final = discard_empty_evidence(corrected, "correction")
            final = final.model_copy(update={"warnings": [*prepared.warnings, *final.warnings]})
            remaining = [
                i
                for i in evidence_issues(corrected, document.content)
                if i.code != "emotion_quote_empty"
            ]
            if remaining:
                raise EmotionEvidenceError(remaining)
        else:
            final = prepared
        # No partial graph result: labels, duplicates and every surviving quote must pass.
        return self.validate_payload(final.model_dump(mode="json"), document), metadata

    label_key = staticmethod(label_key)

    def validate_payload(self, payload, document):
        return validate_emotions(payload, document)

    async def write_layer(self, output, payload):
        await self.store.persist(output, payload)
