"""Composition root for infrastructure adapters and application use cases."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.config import get_settings
from src.services.audio_note_store import FileAudioNoteStore
from src.services.claim_embedding_store import ClaimEmbeddingStore
from src.services.document_embedding_store import DocumentEmbeddingStore
from src.services.document_store import FileDocumentStore
from src.services.embedding_provider import EmbeddingProvider, UnavailableEmbeddingProvider
from src.services.extraction_store import FileExtractionStore
from src.services.graph_store import GraphBackend
from src.services.openai_embedding_provider import OpenAIEmbeddingProvider
from src.services.openai_extractor import OpenAIExtractor
from src.services.openai_reflection_provider import OpenAIReflectionProvider
from src.services.openai_transcription_provider import OpenAITranscriptionProvider
from src.services.reflection_context_store import ReflectionContextStore
from src.services.reflection_provider import ReflectionProvider, UnavailableReflectionProvider
from src.services.reflection_store import FileReflectionStore
from src.services.structured_extractor import (
    StructuredExtractor,
    UnavailableStructuredExtractor,
)
from src.services.transcription_provider import (
    TranscriptionProvider,
    UnavailableTranscriptionProvider,
)
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.embed_documents import EmbedDocument
from src.use_cases.extract_and_persist_document import ExtractAndPersistDocument
from src.use_cases.extract_document import ExtractDocument
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document import IngestDocument
from src.use_cases.ingest_document_file import IngestDocumentFile
from src.use_cases.resolve_question import ResolveQuestion
from src.use_cases.search_semantically import SearchSemantically
from src.use_cases.search_similar_claims import SearchSimilarClaims
from src.use_cases.transcribe_audio_note import CreateAudioNote, TranscribeAudioNote
from src.workspaces.dependencies import WorkspaceRuntime, get_workspace_runtime


async def get_document_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileDocumentStore:
    return runtime.document_store


async def get_audio_note_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileAudioNoteStore:
    return runtime.audio_note_store


async def get_extraction_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileExtractionStore:
    return runtime.extraction_store


@lru_cache
def get_structured_extractor() -> StructuredExtractor:
    """Select a provider adapter without exposing it to routes or use cases."""
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAIExtractor(settings.openai_api_key, settings.openai_model)
    return UnavailableStructuredExtractor(settings.llm_provider)


@lru_cache
def get_transcription_provider() -> TranscriptionProvider:
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAITranscriptionProvider(
            settings.openai_api_key, settings.openai_transcription_model
        )
    return UnavailableTranscriptionProvider(
        settings.llm_provider,
        settings.openai_transcription_model,
    )


async def get_graph_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> GraphBackend:
    return runtime.graph_store


async def get_claim_embedding_store(
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
) -> ClaimEmbeddingStore:
    return graph_store


async def get_document_embedding_store(
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
) -> DocumentEmbeddingStore:
    return graph_store


async def get_reflection_context_store(
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
) -> ReflectionContextStore:
    return graph_store


async def get_reflection_store(
    runtime: Annotated[WorkspaceRuntime, Depends(get_workspace_runtime)],
) -> FileReflectionStore:
    return runtime.reflection_store


@lru_cache
def get_reflection_provider() -> ReflectionProvider:
    settings = get_settings()
    model = settings.openai_reflection_model or settings.openai_model
    if settings.reflection_provider == "openai":
        return OpenAIReflectionProvider(settings.openai_api_key, model)
    return UnavailableReflectionProvider(settings.reflection_provider, model or "unconfigured")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Select an embedding provider independently of the extraction provider."""
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            settings.openai_api_key,
            settings.openai_embedding_model,
            settings.openai_embedding_dimensions,
        )
    return UnavailableEmbeddingProvider(
        settings.embedding_provider,
        settings.openai_embedding_model,
        settings.openai_embedding_dimensions,
    )


def close_graph_store() -> None:
    """HTTP graph clients are request-scoped and hold no process-wide resources."""


async def get_ingest_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
) -> IngestDocument:
    """Build the application operation used by any delivery interface."""
    return IngestDocument(document_store)


async def get_create_audio_note(
    audio_note_store: Annotated[FileAudioNoteStore, Depends(get_audio_note_store)],
) -> CreateAudioNote:
    return CreateAudioNote(audio_note_store, get_settings().audio_max_upload_bytes)


async def get_transcribe_audio_note(
    audio_note_store: Annotated[FileAudioNoteStore, Depends(get_audio_note_store)],
) -> TranscribeAudioNote:
    return TranscribeAudioNote(audio_note_store, get_transcription_provider())


async def get_ingest_document_file(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
) -> IngestDocumentFile:
    """Build the file-upload operation used by HTTP or a future CLI."""
    return IngestDocumentFile(document_store)


async def get_extract_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    extraction_store: Annotated[FileExtractionStore, Depends(get_extraction_store)],
) -> ExtractDocument:
    """Build the extraction operation shared by HTTP and future CLI adapters."""
    return ExtractDocument(document_store, extraction_store, get_structured_extractor())


async def get_extract_and_persist_document(
    extract_document: Annotated[ExtractDocument, Depends(get_extract_document)],
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
) -> ExtractAndPersistDocument:
    """Build the extraction flow that makes completed runs queryable in the graph."""
    return ExtractAndPersistDocument(extract_document, graph_store)


async def get_extract_persist_and_embed_document(
    extract_and_persist: Annotated[
        ExtractAndPersistDocument,
        Depends(get_extract_and_persist_document),
    ],
    claim_embeddings: Annotated[ClaimEmbeddingStore, Depends(get_claim_embedding_store)],
    document_embeddings: Annotated[DocumentEmbeddingStore, Depends(get_document_embedding_store)],
) -> ExtractPersistAndEmbedDocument:
    """Build the default flow that makes extracted claims semantically searchable."""
    return ExtractPersistAndEmbedDocument(
        extract_and_persist,
        EmbedClaims(get_embedding_provider(), claim_embeddings),
        EmbedDocument(get_embedding_provider(), document_embeddings),
    )


async def get_search_similar_claims(
    claim_embeddings: Annotated[ClaimEmbeddingStore, Depends(get_claim_embedding_store)],
) -> SearchSimilarClaims:
    """Build semantic retrieval without exposing providers or graph engines to routes."""
    return SearchSimilarClaims(get_embedding_provider(), claim_embeddings)


async def get_search_semantically(
    claim_embeddings: Annotated[ClaimEmbeddingStore, Depends(get_claim_embedding_store)],
    document_embeddings: Annotated[DocumentEmbeddingStore, Depends(get_document_embedding_store)],
) -> SearchSemantically:
    """Build mixed document and claim retrieval without leaking graph engines to routes."""
    return SearchSemantically(
        get_embedding_provider(),
        claim_embeddings,
        document_embeddings,
    )


async def get_resolve_question(
    similar_claims: Annotated[SearchSimilarClaims, Depends(get_search_similar_claims)],
    reflection_context: Annotated[ReflectionContextStore, Depends(get_reflection_context_store)],
    reflection_store: Annotated[FileReflectionStore, Depends(get_reflection_store)],
) -> ResolveQuestion:
    return ResolveQuestion(
        similar_claims,
        reflection_context,
        get_reflection_provider(),
        reflection_store,
    )


async def get_ingest_and_extract_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    extract_persist_and_embed: Annotated[
        ExtractPersistAndEmbedDocument,
        Depends(get_extract_persist_and_embed_document),
    ],
) -> IngestAndExtractDocument:
    """Build the default processing flow triggered by every new document."""
    return IngestAndExtractDocument(
        IngestDocument(document_store),
        extract_persist_and_embed,
    )


async def get_delete_document(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
    extraction_store: Annotated[FileExtractionStore, Depends(get_extraction_store)],
    graph_store: Annotated[GraphBackend, Depends(get_graph_store)],
):
    from src.use_cases.delete_document import DeleteDocument

    return DeleteDocument(document_store, extraction_store, graph_store)



async def get_list_documents(
    document_store: Annotated[FileDocumentStore, Depends(get_document_store)],
):
    from src.use_cases.list_documents import ListDocuments

    return ListDocuments(document_store)
