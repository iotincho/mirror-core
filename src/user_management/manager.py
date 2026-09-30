"""FastAPI Users configuration hidden behind the local module boundary."""

import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, UUIDIDMixin, exceptions, schemas
from fastapi_users.db import SQLAlchemyUserDatabase

from src.config import get_settings
from src.user_management.database import get_user_db
from src.user_management.models import User

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase, token_secret: str) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = token_secret
        self.verification_token_secret = token_secret

    async def validate_password(
        self,
        password: str,
        user: schemas.BaseUserCreate | User,
    ) -> None:
        if len(password) < 12:
            raise exceptions.InvalidPasswordException(
                reason="Password should be at least 12 characters"
            )
        if user.email.lower() in password.lower():
            raise exceptions.InvalidPasswordException(
                reason="Password should not contain the email address"
            )

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        logger.info("user_registered user_id=%s", user.id)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    token_secret = get_settings().auth_session_secret
    if not token_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    yield UserManager(user_db, token_secret)
