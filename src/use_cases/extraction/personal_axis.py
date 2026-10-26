"""One concrete extractor shared by sample dry runs and deferred active persistence."""

from dataclasses import replace
from uuid import UUID

from src.core.documents.ports import DocumentStore
from src.core.extractors.artifacts import LayerArtifacts
from src.core.extractors.contracts import content_hash
from src.core.extractors.personal_axes.models import (
    AxisSpecification,
    AxisWriteContext,
    Findings,
    FindingsResponse,
)
from src.core.extractors.personal_axes.policies import evidence_issues, label_key
from src.core.extractors.personal_axes.ports import AxisProjection, AxisProvider
from src.use_cases.extraction.base import Extractor


class PersonalAxisExtractor(Extractor):
    name = "personal_axis"

    def __init__(
        self,
        documents: DocumentStore,
        artifacts: LayerArtifacts,
        specification,
        provider: AxisProvider | None = None,
        store: AxisProjection | None = None,
        axis_id: UUID | str | None = None,
        version_id: UUID | str | None = None,
        *,
        write_context: AxisWriteContext | None = None,
    ):
        self.specification = AxisSpecification.model_validate(specification)
        super().__init__(documents, artifacts, self.specification.profile)
        self.provider, self.store = provider, store
        self.axis_id = UUID(str(axis_id)) if axis_id else None
        self.version_id = UUID(str(version_id)) if version_id else None
        self.write_context = write_context or AxisWriteContext()
        self.write_applied = True

    # Temporary API for the reservation binder; removed with its SQL migration in stage 4.
    @property
    def write_order(self):
        return self.write_context.order

    @write_order.setter
    def write_order(self, value):
        self.write_context = replace(self.write_context, order=value)

    @property
    def legacy_versions(self):
        return dict(self.write_context.version_numbers)

    @legacy_versions.setter
    def legacy_versions(self, value):
        self.write_context = replace(self.write_context, version_numbers=tuple(value.items()))

    @property
    def request_config(self):
        return {
            "specification_hash": self.specification.fingerprint,
            "provider": self.specification.provider,
            "model": self.specification.model,
            "axis_id": str(self.axis_id) if self.axis_id else "",
            "version_id": str(self.version_id) if self.version_id else "",
        }

    async def produce(self, document):
        if self.provider is None:
            raise ValueError("axis_provider_required")
        if len(document.content) > self.specification.max_input_chars:
            raise ValueError("axis_input_too_long")
        return await self.provider.extract(document, self.profile)

    async def produce_for_run(self, document, run_id):
        storage = self.artifacts.storage(document.id, run_id)
        identity = str(run_id)
        context = {
            "source": content_hash(document.content),
            "config": self.request_config,
            "profile_hash": self.profile.fingerprint,
        }

        async def response(phase, initial=None, issues=None):
            saved = await storage.read(phase, identity)
            if saved is None:
                if phase == "initial":
                    value, metadata = await self.produce(document)
                else:
                    marker = await storage.read("correction-requested", identity)
                    if marker is not None:
                        raise ValueError("axis_correction_interrupted")
                    await storage.write("correction-requested", identity, context)
                    value, metadata = await self.provider.correct(
                        document, self.profile, initial, issues
                    )
                saved = {
                    "context": context,
                    "response": value.model_dump(mode="json"),
                    "provider": metadata.model_dump(mode="json") if metadata else None,
                }
                await storage.write(phase, identity, saved)
            if saved["context"] != context:
                raise ValueError("run_configuration_changed")
            from src.core.extractors.contracts import ProviderMetadata

            return (
                FindingsResponse.model_validate(saved["response"]),
                ProviderMetadata.model_validate(saved["provider"]) if saved["provider"] else None,
            )

        initial, metadata = await response("initial")
        issues = evidence_issues(initial, document.content)
        if not issues:
            return Findings(findings=initial.findings), metadata
        corrected, metadata = await response("correction", initial, issues)
        if evidence_issues(corrected, document.content):
            raise ValueError("axis_evidence_invalid")
        return Findings(findings=corrected.findings, warnings=["axis_output_corrected"]), metadata

    def validate_payload(self, payload, document):
        result = Findings.model_validate(payload)
        if evidence_issues(result, document.content):
            raise ValueError("axis_evidence_invalid")
        findings = []
        for finding in result.findings:
            tags = {}
            for tag in finding.tags:
                tags.setdefault(label_key(tag), " ".join(tag.split()))
            findings.append(finding.model_copy(update={"tags": list(tags.values())}))
        return result.model_copy(update={"findings": findings})

    async def write_layer(self, output, payload):
        if not self.axis_id or not self.version_id or self.store is None:
            raise ValueError("axis_active_binding_required")
        if output.request_config != self.request_config:
            raise ValueError("axis_binding_mismatch")
        self.write_applied = await self.store.write(
            output,
            payload,
            self.axis_id,
            self.version_id,
            context=self.write_context,
        )
