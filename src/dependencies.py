"""Composition root for infrastructure adapters and application use cases."""

from functools import lru_cache

from src.config import get_settings
from src.graph.neo4j_store import Neo4jGraphStore
from src.services.audio_note_store import FileAudioNoteStore
from src.services.claim_embedding_store import ClaimEmbeddingStore
from src.services.document_embedding_store import DocumentEmbeddingStore
from src.services.document_store import FileDocumentStore
from src.services.embedding_provider import EmbeddingProvider, UnavailableEmbeddingProvider
from src.services.extraction_store import FileExtractionStore
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


@lru_cache
def get_document_store() -> FileDocumentStore:
    """Provide the local development adapter for original documents."""
    return FileDocumentStore(get_settings().documents_path)


@lru_cache
def get_audio_note_store() -> FileAudioNoteStore:
    """Provide durable storage for raw audio and transcription status."""
    return FileAudioNoteStore(get_settings().audio_notes_path)


@lru_cache
def get_extraction_store() -> FileExtractionStore:
    """Provide local, auditable storage for experimental extraction runs."""
    return FileExtractionStore(get_settings().extractions_path)


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


@lru_cache
def get_graph_store() -> Neo4jGraphStore:
    """Provide the Neo4j adapter while keeping Cypher out of application use cases."""
    settings = get_settings()
    return Neo4jGraphStore(
        settings.neo4j_uri,
        settings.neo4j_username,
        settings.neo4j_password,
    )


def get_claim_embedding_store() -> ClaimEmbeddingStore:
    """Reuse Neo4j for the graph and claim-vector persistence boundaries."""
    return get_graph_store()


def get_document_embedding_store() -> DocumentEmbeddingStore:
    """Reuse Neo4j for document-vector persistence and retrieval."""
    return get_graph_store()


def get_reflection_context_store() -> ReflectionContextStore:
    """Expose graph relations without leaking Neo4j into reflection orchestration."""
    return get_graph_store()


@lru_cache
def get_reflection_store() -> FileReflectionStore:
    return FileReflectionStore(get_settings().reflections_path)


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
    """Release the Neo4j driver when the API process stops."""
    graph_store = get_graph_store()
    close = getattr(graph_store, "close", None)
    if close is not None:
        close()
    get_graph_store.cache_clear()


async def get_ingest_document() -> IngestDocument:
    """Build the application operation used by any delivery interface."""
    return IngestDocument(get_document_store())


async def get_create_audio_note() -> CreateAudioNote:
    return CreateAudioNote(get_audio_note_store(), get_settings().audio_max_upload_bytes)


async def get_transcribe_audio_note() -> TranscribeAudioNote:
    return TranscribeAudioNote(get_audio_note_store(), get_transcription_provider())


async def get_ingest_document_file() -> IngestDocumentFile:
    """Build the file-upload operation used by HTTP or a future CLI."""
    return IngestDocumentFile(get_document_store())


async def get_extract_document() -> ExtractDocument:
    """Build the extraction operation shared by HTTP and future CLI adapters."""
    return ExtractDocument(get_document_store(), get_extraction_store(), get_structured_extractor())


async def get_extract_and_persist_document() -> ExtractAndPersistDocument:
    """Build the extraction flow that also makes completed runs queryable in Neo4j."""
    return ExtractAndPersistDocument(await get_extract_document(), get_graph_store())


async def get_extract_persist_and_embed_document() -> ExtractPersistAndEmbedDocument:
    """Build the default flow that makes extracted claims semantically searchable."""
    return ExtractPersistAndEmbedDocument(
        await get_extract_and_persist_document(),
        EmbedClaims(get_embedding_provider(), get_claim_embedding_store()),
        EmbedDocument(get_embedding_provider(), get_document_embedding_store()),
    )


async def get_search_similar_claims() -> SearchSimilarClaims:
    """Build semantic retrieval without exposing providers or Neo4j to routes."""
    return SearchSimilarClaims(get_embedding_provider(), get_claim_embedding_store())


async def get_search_semantically() -> SearchSemantically:
    """Build mixed document and claim retrieval without leaking Neo4j to routes."""
    return SearchSemantically(
        get_embedding_provider(),
        get_claim_embedding_store(),
        get_document_embedding_store(),
    )


async def get_resolve_question() -> ResolveQuestion:
    return ResolveQuestion(
        await get_search_similar_claims(),
        get_reflection_context_store(),
        get_reflection_provider(),
        get_reflection_store(),
    )


async def get_ingest_and_extract_document() -> IngestAndExtractDocument:
    """Build the default processing flow triggered by every new document."""
    return IngestAndExtractDocument(
        IngestDocument(get_document_store()),
        await get_extract_persist_and_embed_document(),
    )

async def get_delete_document():
    from src.use_cases.delete_document import DeleteDocument
    return DeleteDocument(get_document_store(), get_extraction_store(), get_graph_store())

async def get_list_documents():
    from src.use_cases.list_documents import ListDocuments
    return ListDocuments(get_document_store())
