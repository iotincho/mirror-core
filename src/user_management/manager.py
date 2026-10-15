"""FastAPI Users configuration hidden behind the local module boundary."""

import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, UUIDIDMixin, schemas
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import func, select
from sqlalchemy.orm import noload

from src.config import get_settings
from src.user_management.database import get_user_db
from src.user_management.models import User
from src.user_management.passwords import validate_password

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase, token_secret: str) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = token_secret
        self.verification_token_secret = token_secret

    async def authenticate(self, credentials):
        # Serialize verification/hash upgrades with password reset. Otherwise a
        # concurrent legacy-hash upgrade could restore the pre-reset password.
        user = await self.user_db.session.scalar(
            select(User)
            .options(noload(User.oauth_accounts))
            .where(func.lower(User.email) == credentials.username.lower())
            .with_for_update(of=User, key_share=True)
        )
        if user is None:
            self.password_helper.hash(credentials.password)
            return None
        verified, upgraded_hash = self.password_helper.verify_and_update(
            credentials.password, user.hashed_password
        )
        if not verified:
            return None
        changes = {}
        if upgraded_hash is not None:
            changes["hashed_password"] = upgraded_hash
        if user.password_login_enabled is not True:
            changes["password_login_enabled"] = True
        if changes:
            user = await self.user_db.update(user, changes)
        return user

    async def validate_password(
        self,
        password: str,
        user: schemas.BaseUserCreate | User,
    ) -> None:
        validate_password(password, user.email)

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        logger.info("user_registered user_id=%s", user.id)
        # This is an event boundary: user_management neither exposes nor owns the
        # workspace implementation. A provisioning failure is represented in
        # PostgreSQL and can be reconciled without invalidating the new account.
        from src.workspaces.provisioning import provision_workspace_for_user

        try:
            workspace = await provision_workspace_for_user(user.id)
        except Exception:
            # The account has already been committed. Keep registration successful
            # and let the authenticated setup screen offer recovery.
            logger.exception("workspace_registration_failed user_id=%s", user.id)
            return
        logger.info("workspace_registration_result user_id=%s status=%s", user.id, workspace.status)


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
