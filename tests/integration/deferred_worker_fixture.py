"""Test-only provider replacements; filesystem, SQL, Rabbit and graph are real."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from test_deferred_ingestion import FakeProviders

from src.adapters.storage.filesystem.audio_notes import FileAudioNoteStore
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.bootstrap.audio import build_audio_processor as ProcessAudioNote
from src.bootstrap.graph import build_graph_store as ArcadeDBGraphStore
from src.bootstrap.processing import build_source_processor as ProcessDocument
from src.bootstrap.workflow_registry import registry

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
            graph_store=graph,
        )
    finally:
        await graph.close()


def factory(config):
    return providers


registry.definitions[("document", 2)] = ProcessDocument(runtime).definition
registry.definitions[("audio", 2)] = ProcessAudioNote(runtime, factory).definition
