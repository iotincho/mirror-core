"""FastAPI Users configuration hidden behind the local module boundary."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin, schemas
from fastapi_users.exceptions import InvalidPasswordException

from src.core.auth.passwords import InvalidPassword, validate_password

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[Any, UUID]):
    def __init__(self, user_db, token_secret: str, *, authenticate, on_registered) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = token_secret
        self.verification_token_secret = token_secret
        self._authenticate, self._on_registered = authenticate, on_registered

    async def authenticate(self, credentials):
        return await self._authenticate(credentials, self.password_helper)

    async def validate_password(
        self,
        password: str,
        user: schemas.BaseUserCreate | Any,
    ) -> None:
        try:
            validate_password(password, user.email)
        except InvalidPassword as error:
            raise InvalidPasswordException(reason=error.reason) from None

    async def on_after_register(self, user: Any, request: Request | None = None) -> None:
        logger.info("user_registered user_id=%s", user.id)
        # The committed registration event neither exposes nor owns the
        # workspace implementation. A provisioning failure is represented in
        # PostgreSQL and can be reconciled without invalidating the new account.
        try:
            workspace = await self._on_registered(user.id)
        except Exception:
            # The account has already been committed. Keep registration successful
            # and let the authenticated setup screen offer recovery.
            logger.exception("workspace_registration_failed user_id=%s", user.id)
            return
        logger.info("workspace_registration_result user_id=%s status=%s", user.id, workspace.status)
