"""Token-bounded segmentation and recoverable embeddings through injected ports."""

from math import isfinite

from src.core.extractors.contracts import ProviderMetadata, content_hash, digest
from src.core.extractors.document_embeddings import (
    EMBEDDINGS_PROFILE,
    DocumentEmbeddings,
    EmbeddingSection,
)
from src.use_cases.extraction.base import Extractor


def bounded_spans(text: str, maximum: int, token_count):
    """Keep Unicode and source offsets intact; prefer paragraph/line boundaries."""
    if text and token_count(text) <= maximum:
        yield 0, len(text)
        return
    start = 0
    while start < len(text):
        lo, hi = start + 1, min(len(text), start + maximum * 8)
        end = start
        while lo <= hi:
            middle = (lo + hi) // 2
            if token_count(text[start:middle]) <= maximum:
                end, lo = middle, middle + 1
            else:
                hi = middle - 1
        if end == start:
            raise ValueError("embedding_token_budget_too_small")
        if end < len(text):
            boundary = text.rfind("\n", start + (end - start) // 2, end)
            if boundary >= 0:
                end = boundary + 1
        yield start, end
        start = end


class DocumentEmbeddingExtractor(Extractor):
    name = "document_embeddings"

    def __init__(
        self,
        documents,
        artifacts,
        store,
        configuration,
        provider=None,
        profile=EMBEDDINGS_PROFILE,
        force=False,
        *,
        token_count,
    ):
        super().__init__(documents, artifacts, profile)
        self.token_count = token_count
        self.store, self.configuration, self.provider, self.force = (
            store,
            configuration,
            provider,
            force,
        )

    def bounded_spans(self, text, maximum):
        return bounded_spans(text, maximum, self.token_count)

    @property
    def configuration_hash(self):
        return digest(
            {"configuration": self.configuration.model_dump(), "profile": self.profile.fingerprint}
        )

    @property
    def request_config(self):
        return {"configuration_hash": self.configuration_hash, "force": str(self.force).lower()}

    async def produce(self, document):
        existing = await self.store.existing(document.id)
        if existing is not None and not self.force:
            if existing.content_hash != content_hash(document.content) or (
                existing.payload["configuration_hash"] != self.configuration_hash
            ):
                raise ValueError("embedding_reprocessing_requires_force")
            payload = DocumentEmbeddings.model_validate(existing.payload).model_copy(
                update={"force": False}
            )
            return payload, existing.provider
        if self.provider is None:
            raise ValueError("embedding_provider_required")
        content, config = document.content, self.configuration
        spans = [(0, len(content))]
        if self.token_count(content) > min(
            config.segmentation_threshold, config.section_max_tokens
        ):
            spans = []
            for window_start, window_end in self.bounded_spans(content, config.window_tokens):
                window = content[window_start:window_end]
                blocks = list(self.bounded_spans(window, min(256, config.section_max_tokens)))
                result = await self.provider.segment(
                    [window[start:end] for start, end in blocks],
                    self.profile,
                    config.section_target_tokens,
                )
                # Boundaries are hints: repair gaps/overlaps, ignore unusable ranges.
                boundaries = {0, len(blocks)}
                for section in result.sections:
                    if 1 <= section.start_block <= section.end_block <= len(blocks):
                        boundaries.update((section.start_block - 1, section.end_block))
                ordered = sorted(boundaries)
                for first, last in zip(ordered, ordered[1:]):
                    start, end = blocks[first][0], blocks[last - 1][1]
                    spans.append((window_start + start, window_start + end))
        sections = []
        for start, end in spans:
            for local_start, local_end in self.bounded_spans(
                content[start:end], config.section_max_tokens
            ):
                first, last = start + local_start, start + local_end
                text = content[first:last]
                if text.strip():
                    sections.append(
                        {
                            "text": text,
                            "start_char": first,
                            "end_char": last,
                            "tokens": self.token_count(text),
                        }
                    )
        if not sections:
            raise ValueError("embedding_empty_document")
        vectors = []
        for start in range(0, len(sections), 32):
            texts = [section["text"] for section in sections[start : start + 32]]
            vectors.extend(await self.provider.embed(texts, config))
        if len(vectors) != len(sections):
            raise ValueError("embedding_result_count_mismatch")
        payload = DocumentEmbeddings(
            configuration=config,
            configuration_hash=self.configuration_hash,
            force=self.force,
            sections=[
                EmbeddingSection(**section, vector=vector)
                for section, vector in zip(sections, vectors)
            ],
        )
        return payload, ProviderMetadata(provider=config.provider, model=config.model)

    def validate_payload(self, payload, document):
        result = DocumentEmbeddings.model_validate(payload)
        previous = 0
        for section in result.sections:
            if (
                section.start_char < previous
                or section.end_char > len(document.content)
                or document.content[section.start_char : section.end_char] != section.text
                or document.content[previous : section.start_char].strip()
            ):
                raise ValueError("embedding_source_ranges_invalid")
            if (
                section.tokens != self.token_count(section.text)
                or section.tokens > result.configuration.section_max_tokens
            ):
                raise ValueError("embedding_section_token_limit")
            vector = section.vector
            if (
                len(vector) != result.configuration.dimensions
                or not all(isfinite(x) for x in vector)
                or not any(vector)
            ):
                raise ValueError("embedding_vector_invalid")
            previous = section.end_char
        if document.content[previous:].strip():
            raise ValueError("embedding_source_incomplete")
        return result

    def validate_output(self, output, document):
        payload = super().validate_output(output, document)
        expected = digest(
            {"configuration": payload.configuration.model_dump(), "profile": output.profile_hash}
        )
        if payload.configuration_hash != expected or output.request_config != {
            "configuration_hash": expected,
            "force": str(payload.force).lower(),
        }:
            raise ValueError("embedding_configuration_mismatch")
        return payload

    async def write_layer(self, output, payload):
        await self.store.persist(output, payload)
