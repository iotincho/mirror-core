"""Workspace identity, state and provisioning targets without ORM or credentials in repr."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkspaceStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"
    SUSPENDED = "suspended"


@dataclass
class Workspace:
    user_id: UUID
    arcadedb_instance_key: str
    database_name: str
    graph_username: str
    graph_secret_ciphertext: str = field(repr=False)
    status: str = WorkspaceStatus.PENDING
    schema_version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    provisioned_at: datetime | None = None
    last_error_code: str | None = None
    last_error: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ProvisioningTarget:
    user_id: UUID
    database_name: str
    graph_username: str
    graph_secret_ciphertext: str = field(repr=False)


@dataclass(frozen=True)
class ResolvedWorkspace:
    workspace: Workspace
    graph_secret: str = field(repr=False)


class WorkspaceUnavailable(RuntimeError):
    def __init__(self, detail="Personal workspace is unavailable"):
        super().__init__(detail)
        self.detail = detail


class WorkspaceProvisioningError(RuntimeError):
    """Remote provisioning failed; public access must remain unavailable."""
