"""Safe runtime workspace contract, deliberately free of credentials."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from src.core.audio.ports import AudioNoteStore
from src.core.documents.ports import DocumentStore
from src.core.graph.ports import GraphBackend


@dataclass(frozen=True)
class UserWorkspaceContext:
    user_id: UUID
    arcadedb_instance_key: str
    database_name: str
    graph_username: str
    filesystem_root: Path


@dataclass(frozen=True)
class WorkspaceBinding:
    context: UserWorkspaceContext
    graph_secret: str = field(repr=False)


@dataclass(frozen=True)
class WorkspaceRuntime:
    context: UserWorkspaceContext
    document_store: DocumentStore
    audio_note_store: AudioNoteStore
    graph_store: GraphBackend
