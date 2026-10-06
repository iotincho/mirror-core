"""Test-only provider replacements; filesystem, SQL, Rabbit and graph are real."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from test_deferred_ingestion import FakeProviders

from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.processing.runtime import registry
from src.services.audio_note_store import FileAudioNoteStore
from src.services.document_store import FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.use_cases.process_audio_note import ProcessAudioNote
from src.use_cases.process_document import ProcessDocument

providers = FakeProviders()


@asynccontextmanager
async def runtime(user_id):
    root = Path(os.environ["PROCESSING_TEST_WORKSPACE_ROOT"])
    graph = ArcadeDBGraphStore(
        os.environ["PROCESSING_TEST_ARCADEDB_URL"],
        "processing_test",
        "root",
        os.getenv("PROCESSING_TEST_ARCADEDB_PASSWORD", "processing-test"),
    )
    try:
        yield SimpleNamespace(
            context=SimpleNamespace(user_id=user_id, filesystem_root=root),
            document_store=FileDocumentStore(root / "documents"),
            audio_note_store=FileAudioNoteStore(root / "audio-notes"),
            extraction_store=FileExtractionStore(root / "extractions"),
            graph_store=graph,
        )
    finally:
        await graph.close()


def factory(config):
    return providers


registry.definitions[("document", 2)] = ProcessDocument(runtime).definition
registry.definitions[("audio", 2)] = ProcessAudioNote(runtime, factory).definition
