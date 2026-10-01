"""Safe runtime workspace contract, deliberately free of credentials."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class UserWorkspaceContext:
    user_id: UUID
    arcadedb_instance_key: str
    database_name: str
    graph_username: str
    filesystem_root: Path
