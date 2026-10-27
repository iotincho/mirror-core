"""Reauthorize long-lived streams without retaining a database session."""

from src.core.auth.session import SessionExpired, SessionLookup
from src.core.workspaces.models import WorkspaceUnavailable


class AuthorizeStream:
    def __init__(self, sessions: SessionLookup, instance_key: str):
        self.sessions, self.instance_key = sessions, instance_key

    async def execute(self, token):
        if not token:
            raise SessionExpired()
        owner = await self.sessions.lookup(token)
        if owner is None:
            raise SessionExpired()
        if owner.workspace_status != "active" or owner.instance_key != self.instance_key:
            raise WorkspaceUnavailable("Personal workspace is unavailable")
        return owner.id
