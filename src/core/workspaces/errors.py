"""Workspace credential recovery failure, without cryptography dependencies."""


class WorkspaceSecretError(RuntimeError):
    """Raised when a workspace credential cannot be protected or recovered."""
