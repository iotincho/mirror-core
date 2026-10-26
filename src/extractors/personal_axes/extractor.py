"""One concrete extractor shared by sample dry runs and deferred active persistence."""

from src.core.extractors.contracts import content_hash
from src.extractors.personal_axes.contracts import (
    AxisSpecification,
    Findings,
    FindingsResponse,
    label_key,
)
from src.use_cases.extraction.base import Extractor


def evidence_issues(response, content):
    issues = []
    for index, finding in enumerate(response.findings):
        if not finding.title.strip() or not finding.content.strip():
            issues.append({"code": "finding_empty", "finding": index})
        if not finding.tags or any(not tag.strip() or len(tag) > 160 for tag in finding.tags):
            issues.append({"code": "finding_tags_invalid", "finding": index})
        if not finding.evidence:
            issues.append({"code": "finding_evidence_missing", "finding": index})
        seen = set()
        for position, evidence in enumerate(finding.evidence):
            quote = evidence.quote
            offset, matches = 0, 0
            if quote.strip():
                while (start := content.find(quote, offset)) >= 0:
                    matches += 1
                    offset = start + 1
            if matches != 1 or quote in seen:
                issues.append(
                    {
                        "code": "finding_evidence_invalid",
                        "finding": index,
                        "evidence": position,
                        "matches": matches,
                    }
                )
            seen.add(quote)
    return issues


class PersonalAxisExtractor(Extractor):
    name = "personal_axis"

    def __init__(
        self,
        documents,
        artifacts,
        specification,
        provider=None,
        store=None,
        axis_id=None,
        version_id=None,
    ):
        self.specification = AxisSpecification.model_validate(specification)
        super().__init__(documents, artifacts, self.specification.profile)
        self.provider, self.store = provider, store
        self.axis_id, self.version_id = axis_id, version_id
        self.write_order, self.legacy_versions = None, {}
        self.write_applied = True

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
            write_order=self.write_order,
            legacy_versions=self.legacy_versions,
        )
