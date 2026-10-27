"""Revocable cookie authentication backed by PostgreSQL."""

from fastapi_users.authentication.strategy.db import DatabaseStrategy

from src.core.auth.identity import session_is_current


class InvitationDatabaseStrategy(DatabaseStrategy):
    def __init__(self, database, lifetime_seconds, *, deactivate_session):
        super().__init__(database, lifetime_seconds=lifetime_seconds)
        self._deactivate_session = deactivate_session

    def _create_access_token_dict(self, user):
        return {**super()._create_access_token_dict(user), "session_version": user.session_version}

    async def read_token(self, token, user_manager):
        user = await super().read_token(token, user_manager)
        if user is None:
            return None
        access_token = await self.database.get_by_token(token)
        if access_token is None or not session_is_current(
            access_token.session_version, user.session_version
        ):
            return None
        return user

    async def destroy_token(self, token: str, user) -> None:
        await self._deactivate_session(user.id, token)
        await super().destroy_token(token, user)
