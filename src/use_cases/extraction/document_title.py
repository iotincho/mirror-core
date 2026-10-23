"""Title generation and recoverable persistence through workspace-bound ports."""

from src.core.documents.ports import DocumentStore
from src.core.extractors.artifacts import LayerArtifacts
from src.core.extractors.contracts import ExtractorProfile
from src.core.extractors.document_title import (
    TITLE_PROFILE,
    DocumentTitle,
    DocumentTitleProvider,
    DocumentTitleStore,
)
from src.use_cases.extraction.base import Extractor


class DocumentTitleExtractor(Extractor):
    name = "document_title"

    def __init__(
        self,
        documents: DocumentStore,
        artifacts: LayerArtifacts,
        store: DocumentTitleStore,
        provider: DocumentTitleProvider | None = None,
        profile: ExtractorProfile = TITLE_PROFILE,
    ):
        super().__init__(documents, artifacts, profile)
        self.store, self.provider = store, provider

    @property
    def request_config(self):
        if self.provider is None:
            return {}
        return {"provider": self.provider.provider_name, "model": self.provider.model_name}

    async def extract(self, document, *, dry_run=True, run_id=None):
        current = await self.documents.get(document.id)
        if current.content != document.content:
            raise ValueError("source_changed")
        return await super().extract(current, dry_run=dry_run, run_id=run_id)

    async def produce(self, document):
        # Read the canonical title, rather than a potentially stale caller snapshot.
        current = await self.documents.get(document.id)
        if current.title and current.title.strip():
            # Imported titles need not follow the generation prompt's formatting rules.
            return DocumentTitle.model_construct(title=current.title), None
        if self.provider is None:
            raise ValueError("title_provider_required")
        return await self.provider.extract(document, self.profile)

    def validate_payload(self, payload, document):
        if document.title and document.title.strip() and payload == {"title": document.title}:
            # An existing title is authoritative; never rewrite it to enforce new style rules.
            return DocumentTitle.model_construct(title=document.title)
        return DocumentTitle.model_validate(payload)

    async def write_layer(self, output, payload):
        current = await self.documents.get(output.document_id)
        self.validate_output(output, current)
        if not current.title or not current.title.strip():
            current = await self.documents.update_title(current.id, payload.title)
        # Canonical file first. A failed graph write is recoverable from the saved artifact;
        # a replay also respects any title assigned since extraction.
        await self.store.update_title(current)
